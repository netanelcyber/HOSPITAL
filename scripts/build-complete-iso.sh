#!/bin/bash

# Build complete DSS ISO for VirtualBox
# This creates a bootable ISO with everything included

set -e

PROJECT_ROOT="/home/user/HOSPITAL"
BUILD_DIR="${PROJECT_ROOT}/build"
ISO_WORK="${BUILD_DIR}/iso-work"
ISO_OUTPUT="${BUILD_DIR}/dss-hospital.iso"

echo "Building DSS Complete ISO..."
echo "=========================================="

# Create working directories
rm -rf "$ISO_WORK" 2>/dev/null || true
mkdir -p "$ISO_WORK/boot"
mkdir -p "$ISO_WORK/dss"

# Copy all system files
echo "Copying system files..."
cp -r "$PROJECT_ROOT/build/dss-vbox-package/system" "$ISO_WORK/dss/"
cp -r "$PROJECT_ROOT/build/dss-vbox-package/docker" "$ISO_WORK/dss/"
cp -r "$PROJECT_ROOT/build/dss-vbox-package/scripts" "$ISO_WORK/dss/"
cp -r "$PROJECT_ROOT/build/dss-vbox-package/docs" "$ISO_WORK/dss/"

# Copy source code
echo "Copying source code..."
mkdir -p "$ISO_WORK/dss/src"
cp -r "$PROJECT_ROOT/src" "$ISO_WORK/dss/" 2>/dev/null || echo "Source files optional"
cp "$PROJECT_ROOT/package.json" "$ISO_WORK/dss/" 2>/dev/null || true
cp "$PROJECT_ROOT/tsconfig.json" "$ISO_WORK/dss/" 2>/dev/null || true

# Create boot README
cat > "$ISO_WORK/README.txt" << 'EOF'
================================================================================
  Distributed SharePoint System - Hospital Edition
================================================================================

QUICK START:
1. Mount ISO in VirtualBox
2. Boot and install Ubuntu 22.04 server
3. After boot, run: tar -xzf dss-system.tar.gz && cd dss && ./install.sh
4. Access at: http://<ip>:3000

SYSTEM CONTENTS:
- Complete DSS application (Docker-ready)
- Configuration files
- Documentation
- Installation scripts
- Source code

FEATURES:
✓ Document Management (nested folders)
✓ PACS Medical Imaging
✓ FHIR Healthcare Standards
✓ Real-time Notifications
✓ VM Orchestration
✓ HIPAA Compliance
✓ Security Gateway
✓ Full Audit Logging

REQUIREMENTS:
- VirtualBox 7.0+
- 4GB+ RAM
- 20GB+ disk space

DEFAULT PORTS:
- API Server: 3000
- PACS DICOM: 11112
- PostgreSQL: 5432
- Redis: 6379
- MinIO: 9000/9001

SETUP:
1. Extract: tar -xzf dss-vbox-package.tar.gz
2. Start: cd dss-vbox-package && ./scripts/start.sh
3. Verify: curl http://localhost:3000/health

More info: See docs/README.md and SETUP-VBOX.md

================================================================================
EOF

# Create installation script
cat > "$ISO_WORK/install-dss.sh" << 'EOF'
#!/bin/bash
set -e

echo "Installing Distributed SharePoint System..."

# Update system
sudo apt-get update
sudo apt-get upgrade -y

# Install Docker
sudo apt-get install -y docker.io docker-compose

# Add current user to docker group
sudo usermod -aG docker $USER

# Create DSS directory
mkdir -p ~/dss-system
cd ~/dss-system

# Extract package if not already extracted
if [ ! -d "dss-vbox-package" ]; then
  if [ -f "dss-vbox-package.tar.gz" ]; then
    tar -xzf dss-vbox-package.tar.gz
  else
    echo "No package found. Please copy dss-vbox-package.tar.gz to this directory."
    exit 1
  fi
fi

# Start services
cd dss-vbox-package
./scripts/start.sh

echo "Installation complete!"
echo "Access at: http://localhost:3000"

EOF

chmod +x "$ISO_WORK/install-dss.sh"

# Create Grub boot menu configuration
mkdir -p "$ISO_WORK/boot/grub"
cat > "$ISO_WORK/boot/grub/grub.cfg" << 'EOF'
set default="0"
set timeout="30"

menuentry "DSS Hospital System - Ubuntu 22.04" {
  echo "Distributed SharePoint System - Hospital Edition"
  echo ""
  echo "This ISO contains the complete DSS application."
  echo ""
  echo "After booting:"
  echo "1. Install Ubuntu 22.04 server from official ISO"
  echo "2. Copy dss-vbox-package.tar.gz to system"
  echo "3. Run: ./install-dss.sh"
  echo ""
  echo "Press ENTER to continue..."
  read
}

EOF

# Create ISO structure info
cat > "$ISO_WORK/CONTENTS.txt" << 'EOF'
DSS Hospital System ISO Contents
=================================

/dss-vbox-package/
  - docker/          : Docker images and configuration
  - system/          : Docker Compose and configs
  - scripts/         : Start/stop/status scripts
  - docs/            : Documentation and guides
  - src/             : TypeScript source code (optional)

/install-dss.sh     : Automated installation script

/README.txt         : Quick start guide

/boot/              : Boot configuration

INSTALLATION STEPS:
1. Boot this ISO in VirtualBox
2. Install Ubuntu 22.04 server (from original Ubuntu ISO)
3. After Ubuntu boots, run the install-dss.sh script
4. System will start automatically
5. Access at http://localhost:3000

FEATURES INCLUDED:
- Complete API server
- PostgreSQL database
- Redis cache
- MinIO object storage
- PACS imaging system
- FHIR healthcare support
- Real-time notifications
- HIPAA compliance
- Security gateway
- VM orchestration

For more information, see docs/README.md

EOF

# Try to create ISO using available tools
echo "Creating ISO image..."

if command -v mkisofs &> /dev/null; then
  echo "Using mkisofs..."
  mkisofs -R -J -V "DSS-HOSPITAL" \
    -b boot/grub/i386-pc/eltorito.img \
    -no-emul-boot -boot-load-size 4 \
    -boot-info-table -o "$ISO_OUTPUT" "$ISO_WORK"

elif command -v xorriso &> /dev/null; then
  echo "Using xorriso..."
  xorriso -as mkisofs -R -J -V "DSS-HOSPITAL" \
    -o "$ISO_OUTPUT" "$ISO_WORK"

else
  # Fallback: Create a tar archive instead
  echo "ISO tools not available, creating tar archive instead..."
  cd "$BUILD_DIR"
  tar -czf "dss-hospital.tar.gz" iso-work/
  echo "Created: dss-hospital.tar.gz"
  ls -lh "dss-hospital.tar.gz"
  exit 0
fi

# Show result
if [ -f "$ISO_OUTPUT" ]; then
  echo ""
  echo "=========================================="
  echo "ISO Created Successfully!"
  echo "=========================================="
  echo ""
  echo "File: $ISO_OUTPUT"
  echo "Size: $(du -h "$ISO_OUTPUT" | cut -f1)"
  echo ""
  echo "To use with VirtualBox:"
  echo "1. Create new VM (Linux 64-bit)"
  echo "2. Allocate 4+ CPUs, 8GB+ RAM, 50GB+ disk"
  echo "3. Attach ISO to DVD drive"
  echo "4. Boot and install Ubuntu 22.04"
  echo "5. Run install-dss.sh script"
  echo ""
  echo "System will be available at:"
  echo "  http://localhost:3000"
  echo ""
else
  echo "Failed to create ISO. Check if mkisofs or xorriso is installed:"
  echo "  sudo apt-get install mkisofs xorriso"
  exit 1
fi

