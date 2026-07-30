#!/bin/bash

# Build ISO for VirtualBox testing
# This script creates a bootable ISO with DSS pre-installed

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
ISO_DIR="${PROJECT_ROOT}/build/iso"
ISO_OUTPUT="${PROJECT_ROOT}/build/dss-system.iso"

echo "Building DSS ISO for VirtualBox..."

# Create build directory
mkdir -p "$ISO_DIR"

# Download Ubuntu minimal ISO or use existing
UBUNTU_ISO="${ISO_DIR}/ubuntu-22.04-minimal.iso"
if [ ! -f "$UBUNTU_ISO" ]; then
  echo "Downloading Ubuntu 22.04 minimal ISO..."
  # You can replace this with a specific Ubuntu minimal ISO URL
  echo "Note: Manual ISO download may be required. Place at: $UBUNTU_ISO"
fi

# Create a filesystem for the ISO
mkdir -p "${ISO_DIR}/rootfs"

# Copy Docker artifacts
echo "Preparing Docker images for ISO..."
docker save dss-system:latest | gzip > "${ISO_DIR}/dss-image.tar.gz"

# Copy docker-compose and related files
cp "${PROJECT_ROOT}/docker-compose.yml" "${ISO_DIR}/"
cp "${PROJECT_ROOT}/.env.example" "${ISO_DIR}/.env"
cp -r "${PROJECT_ROOT}/scripts" "${ISO_DIR}/"

# Create boot script
cat > "${ISO_DIR}/boot-system.sh" << 'EOF'
#!/bin/bash

# Boot script for DSS System

echo "Starting Distributed SharePoint System..."

# Load Docker image
docker load < dss-image.tar.gz

# Start services
docker-compose up -d

echo "DSS System started!"
echo "Access at http://localhost:3000"
echo "API available at http://localhost:3000/api/v1"
EOF

chmod +x "${ISO_DIR}/boot-system.sh"

# Create ISO using grub-mkrescue or xorriso (if available)
if command -v grub-mkrescue &> /dev/null; then
  echo "Building ISO with GRUB..."
  mkdir -p "${ISO_DIR}/iso/boot/grub"

  # Copy GRUB configuration
  cat > "${ISO_DIR}/iso/boot/grub/grub.cfg" << 'EOF'
menuentry 'Distributed SharePoint System' {
  linux /vmlinuz ro quiet
  initrd /initrd.img
}
EOF

  # Build ISO
  grub-mkrescue -o "$ISO_OUTPUT" "${ISO_DIR}/iso"
elif command -v xorriso &> /dev/null; then
  echo "Building ISO with xorriso..."
  xorriso -as mkisofs -R -J -joliet-long \
    -o "$ISO_OUTPUT" "${ISO_DIR}"
else
  echo "Error: grub-mkrescue or xorriso not found!"
  echo "Install with: apt-get install grub-pc xorriso"
  exit 1
fi

echo "ISO built successfully: $ISO_OUTPUT"
echo ""
echo "To test with VirtualBox:"
echo "  VBoxManage createvm --name DSS --ostype Linux --register"
echo "  VBoxManage modifyvm DSS --cpus 4 --memory 4096"
echo "  VBoxManage storageattach DSS --storagectl SATA --port 0 --device 0 --type dvddrive --medium $ISO_OUTPUT"
echo "  VBoxManage startvm DSS --type gui"
