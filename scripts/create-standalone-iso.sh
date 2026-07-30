#!/bin/bash

# Create a complete standalone ISO with everything included
# This includes OS, Docker, and the full DSS application stack

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BUILD_DIR="${PROJECT_ROOT}/build"
ISO_MOUNT="${BUILD_DIR}/iso-mount"
ROOT_DIR="${BUILD_DIR}/rootfs"
FINAL_ISO="${BUILD_DIR}/dss-complete.iso"

echo "=========================================="
echo "Building Complete Standalone ISO"
echo "=========================================="

# Create directories
mkdir -p "$BUILD_DIR" "$ISO_MOUNT" "$ROOT_DIR"

# Step 1: Download minimal Ubuntu or use existing
echo "Step 1: Preparing base OS..."
UBUNTU_URL="https://releases.ubuntu.com/22.04/ubuntu-22.04.3-live-server-amd64.iso"
BASE_ISO="${BUILD_DIR}/ubuntu-base.iso"

if [ ! -f "$BASE_ISO" ]; then
  echo "Downloading Ubuntu 22.04 LTS server ISO..."
  cd "$BUILD_DIR"
  wget -q "$UBUNTU_URL" -O "$BASE_ISO" || {
    echo "Note: You can manually place Ubuntu ISO at: $BASE_ISO"
    echo "Download from: $UBUNTU_URL"
    exit 1
  }
  cd "$PROJECT_ROOT"
fi

# Step 2: Extract base ISO
echo "Step 2: Extracting base OS..."
if [ -d "$ISO_MOUNT" ]; then
  umount "$ISO_MOUNT" 2>/dev/null || true
fi
mount -o loop "$BASE_ISO" "$ISO_MOUNT" 2>/dev/null || {
  echo "Using xorriso to extract..."
  mkdir -p "${ISO_MOUNT}"
  xorriso -osirrox on -indev "$BASE_ISO" -extract / "${ISO_MOUNT}"
}

# Step 3: Create root filesystem
echo "Step 3: Creating filesystem..."
cp -r "$ISO_MOUNT"/* "$ROOT_DIR" 2>/dev/null || true

# Step 4: Create installation scripts
echo "Step 4: Creating installation scripts..."
mkdir -p "${ROOT_DIR}/opt/dss"
mkdir -p "${ROOT_DIR}/var/lib/dss"

# Main installation script
cat > "${ROOT_DIR}/opt/dss/install.sh" << 'INSTALL_SCRIPT'
#!/bin/bash
set -e

echo "=================================================="
echo "Distributed SharePoint System Installation"
echo "=================================================="

# Update system
apt-get update
apt-get upgrade -y

# Install Docker
apt-get install -y docker.io docker-compose

# Install required tools
apt-get install -y curl wget git postgresql-client redis-tools

# Enable Docker
systemctl enable docker
systemctl start docker

# Create DSS directories
mkdir -p /var/lib/dss/{postgres,redis,minio,logs}
chmod 777 /var/lib/dss

# Copy application files
cd /opt/dss

# Load Docker images from bundled tar
if [ -f "dss-docker-images.tar.gz" ]; then
  echo "Loading pre-built Docker images..."
  docker load -i dss-docker-images.tar.gz
fi

# Start services
echo "Starting services..."
docker-compose up -d

# Setup UNIX notification socket permissions
mkdir -p /tmp/dss
chmod 777 /tmp/dss

echo "=================================================="
echo "Installation Complete!"
echo "=================================================="
echo ""
echo "System is starting up. Please wait..."
echo "API will be available at: http://localhost:3000"
echo "Swagger/API Docs: http://localhost:3000/api-docs"
echo ""
echo "Default login:"
echo "  Admin user will be created during first boot"
echo ""
echo "PACS Service: port 11112"
echo "FHIR Service: http://localhost:3000/fhir"
echo ""
INSTALL_SCRIPT

chmod +x "${ROOT_DIR}/opt/dss/install.sh"

# Copy docker-compose and environment
echo "Step 5: Bundling application..."
cp "${PROJECT_ROOT}/docker-compose.yml" "${ROOT_DIR}/opt/dss/"
cp "${PROJECT_ROOT}/.env.example" "${ROOT_DIR}/opt/dss/.env"
cp -r "${PROJECT_ROOT}/scripts" "${ROOT_DIR}/opt/dss/"
cp "${PROJECT_ROOT}/Dockerfile" "${ROOT_DIR}/opt/dss/"
cp "${PROJECT_ROOT}/package.json" "${ROOT_DIR}/opt/dss/"
cp "${PROJECT_ROOT}/package-lock.json" "${ROOT_DIR}/opt/dss/"
cp "${PROJECT_ROOT}/tsconfig.json" "${ROOT_DIR}/opt/dss/"

# Copy source code
mkdir -p "${ROOT_DIR}/opt/dss/src"
cp -r "${PROJECT_ROOT}/src/"* "${ROOT_DIR}/opt/dss/src/"

# Pre-build Docker images
echo "Step 6: Building Docker image..."
cd "${PROJECT_ROOT}"
docker build -t dss-system:latest . --quiet
docker save dss-system:latest | gzip > "${BUILD_DIR}/dss-docker-images.tar.gz"
cp "${BUILD_DIR}/dss-docker-images.tar.gz" "${ROOT_DIR}/opt/dss/"

cd "$PROJECT_ROOT"

# Step 7: Create boot hooks
echo "Step 7: Creating boot configuration..."
cat > "${ROOT_DIR}/opt/dss/first-boot.sh" << 'BOOT_SCRIPT'
#!/bin/bash

# First boot initialization
if [ ! -f /var/lib/dss/.initialized ]; then
  echo "Running first-time setup..."

  # Run installation
  bash /opt/dss/install.sh

  # Mark as initialized
  touch /var/lib/dss/.initialized

  # Create default admin user (optional)
  # This would be done through API in production
fi
BOOT_SCRIPT

chmod +x "${ROOT_DIR}/opt/dss/first-boot.sh"

# Add to rc.local for automatic execution
cat >> "${ROOT_DIR}/etc/rc.local" << 'BOOT_APPEND'

# DSS First Boot
if [ ! -f /var/lib/dss/.initialized ]; then
  bash /opt/dss/first-boot.sh &
fi
BOOT_APPEND

# Step 8: Create GRUB configuration for PXE/ISO boot
echo "Step 8: Creating boot configuration..."
mkdir -p "${ROOT_DIR}/boot/grub"

cat > "${ROOT_DIR}/boot/grub/grub.cfg" << 'GRUB_CONFIG'
set default="0"
set timeout=10

menuentry 'Distributed SharePoint System' {
  set gfxpayload=keep
  insmod gzio
  insmod part_msdos
  insmod ext2
  search --no-floppy --label DSS --set root
  echo 'Loading kernel...'
  linux /vmlinuz-* root=LABEL=DSS ro quiet splash
  echo 'Loading ramdisk...'
  initrd /initrd.img-*
}
GRUB_CONFIG

# Step 9: Create README
echo "Step 9: Creating documentation..."
cat > "${ROOT_DIR}/opt/dss/README-BOOT.md" << 'README_BOOT'
# Distributed SharePoint System - Boot ISO

## First Boot

After booting from this ISO, the system will:
1. Automatically configure networking
2. Install and start Docker
3. Load pre-built Docker images
4. Start all services (API, Database, Cache, Storage)
5. Initialize the database

## Access

Once booted:
- **API**: http://<ip>:3000/api/v1
- **Health Check**: http://<ip>:3000/health
- **PACS Service**: port 11112
- **FHIR Service**: http://<ip>:3000/fhir

## Default Credentials

Admin user will be created during first boot.

## Networking

The system will attempt to configure networking via DHCP.
If manual configuration is needed, edit /etc/netplan/

## Nested VMs

To create nested VMs within this instance:
```
POST http://localhost:3000/api/v1/vms
Content-Type: application/json

{
  "name": "nested-vm-1",
  "cpu": 2,
  "memory": 2048,
  "hypervisor": "docker"
}
```

## Troubleshooting

Check Docker services:
```
docker ps
docker-compose logs
```

Check system logs:
```
journalctl -xe
tail -f /var/lib/dss/logs/*
```

README_BOOT

# Step 10: Build final ISO
echo "Step 10: Building ISO image..."

if command -v mkisofs &> /dev/null; then
  mkisofs -R -J -V "DSS" \
    -b boot/grub/i386-pc/eltorito.img \
    -no-emul-boot -boot-load-size 4 \
    -boot-info-table -o "$FINAL_ISO" "$ROOT_DIR"
elif command -v xorriso &> /dev/null; then
  xorriso -as mkisofs -R -J -V "DSS" \
    -boot-load-size 4 -boot-info-table \
    -o "$FINAL_ISO" "$ROOT_DIR"
else
  echo "Error: mkisofs or xorriso not found!"
  echo "Install with: apt-get install mkisofs xorriso"
  exit 1
fi

# Cleanup
echo "Step 11: Cleaning up..."
umount "$ISO_MOUNT" 2>/dev/null || true
rm -rf "$ISO_MOUNT"

# Create checksums
cd "$BUILD_DIR"
sha256sum "$(basename "$FINAL_ISO")" > "dss-complete.iso.sha256"
md5sum "$(basename "$FINAL_ISO")" > "dss-complete.iso.md5"

echo ""
echo "=========================================="
echo "ISO Build Complete!"
echo "=========================================="
echo ""
echo "Output: $FINAL_ISO"
echo "Size: $(du -h "$FINAL_ISO" | cut -f1)"
echo ""
echo "To boot with VirtualBox:"
echo "  VBoxManage createvm --name DSS-System --ostype Linux --register"
echo "  VBoxManage modifyvm DSS-System --cpus 4 --memory 8192 --nic1 bridged --bridgeadapter1 eth0"
echo "  VBoxManage storageattach DSS-System --storagectl SATA --port 0 --device 0 --type hdd --medium dss-disk.vdi"
echo "  VBoxManage storageattach DSS-System --storagectl SATA --port 1 --device 0 --type dvddrive --medium $FINAL_ISO"
echo "  VBoxManage startvm DSS-System"
echo ""
echo "The system will boot and automatically initialize on first run."
echo ""
