# 🖥️ DSS Hospital System - ISO Build Guide

## 📥 Downloads Available

### Option 1: Ready-to-Use Package (Recommended)
**File:** `dss-vbox-package.tar.gz` (12KB)

- Includes Docker Compose setup
- All configuration files
- Installation scripts
- Ready to deploy immediately

**Quick Start:**
```bash
tar -xzf dss-vbox-package.tar.gz
cd dss-vbox-package
./scripts/start.sh
```

### Option 2: Complete System Archive
**File:** `dss-hospital.tar.gz` (36KB)

- All application files
- Source code included
- Documentation
- Ready for VirtualBox deployment

**Extract:**
```bash
tar -xzf dss-hospital.tar.gz
cd iso-work/dss-vbox-package
./scripts/start.sh
```

---

## 🛠️ Building a Native ISO (On Your System)

If you want a complete bootable ISO, follow these steps on your Linux system:

### Prerequisites
```bash
# Ubuntu/Debian
sudo apt-get install xorriso grub-pc git

# RHEL/CentOS
sudo dnf install xorriso grub2-tools git
```

### Build Steps

#### 1. Clone Repository
```bash
git clone https://github.com/netanelcyber/HOSPITAL.git
cd HOSPITAL
git checkout claude/distributed-sharepoint-system-kim830
```

#### 2. Download Base ISO
```bash
cd build
wget https://releases.ubuntu.com/22.04/ubuntu-22.04.3-live-server-amd64.iso -O ubuntu-base.iso
# Or use your preferred Linux ISO
```

#### 3. Build DSS ISO
```bash
bash ../scripts/build-complete-iso.sh
```

#### 4. Use the ISO
```bash
# Create VM
VBoxManage createvm --name DSS-Hospital --ostype Linux_64 --register

# Configure
VBoxManage modifyvm DSS-Hospital \
  --cpus 4 --memory 8192 --nic1 bridged

# Attach ISO
VBoxManage storageattach DSS-Hospital \
  --storagectl SATA --port 0 --device 0 \
  --type dvddrive --medium dss-hospital.iso

# Start
VBoxManage startvm DSS-Hospital
```

---

## 🚀 Deployment Methods

### Method 1: Docker Compose (Fastest)
**Time:** 5 minutes
**Requirements:** Docker, Docker Compose

```bash
tar -xzf dss-vbox-package.tar.gz
cd dss-vbox-package
./scripts/start.sh
# Access: http://localhost:3000
```

### Method 2: VirtualBox with Docker
**Time:** 15-20 minutes
**Requirements:** VirtualBox, 4GB RAM, 50GB disk

```bash
# 1. Boot Ubuntu ISO in VirtualBox
# 2. Install Docker: sudo apt-get install docker.io
# 3. Extract package
# 4. Run: ./scripts/start.sh
```

### Method 3: Native ISO (Custom)
**Time:** 30 minutes
**Requirements:** Linux system with xorriso, wget

```bash
# Follow "Building a Native ISO" section above
```

---

## 📋 System Architecture

```
┌─────────────────────────────────────────┐
│    Your Computer / VirtualBox           │
├─────────────────────────────────────────┤
│                                         │
│  ┌─────────────────────────────────┐   │
│  │   Docker Container System       │   │
│  │  ┌─────────────────────────────┐│   │
│  │  │   DSS API Server (3000)    ││   │
│  │  │   - Document Management   ││   │
│  │  │   - PACS Imaging          ││   │
│  │  │   - FHIR Healthcare       ││   │
│  │  │   - Notifications         ││   │
│  │  └─────────────────────────────┘│   │
│  │  ┌─────────────────────────────┐│   │
│  │  │   PostgreSQL (5432)        ││   │
│  │  │   Redis (6379)             ││   │
│  │  │   MinIO Storage (9000)     ││   │
│  │  └─────────────────────────────┘│   │
│  └─────────────────────────────────┘   │
│                                         │
└─────────────────────────────────────────┘
```

---

## 🔧 Configuration

Before starting, edit `.env`:

```bash
# Database
DB_HOST=postgres
DB_PASSWORD=postgres

# Storage
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin

# Features
PACS_ENABLED=true
FHIR_ENABLED=false  # Set true for healthcare
```

---

## ✅ Verification

After starting, verify everything works:

```bash
# Health check
curl http://localhost:3000/health

# API status
curl http://localhost:3000/api/v1/status

# Security status
curl http://localhost:3000/security/status

# Service status
docker-compose ps
```

---

## 📊 File Sizes

| File | Size | Type |
|------|------|------|
| dss-vbox-package.tar.gz | 12 KB | Package |
| dss-hospital.tar.gz | 36 KB | Archive |
| docker-image | ~500 MB | When loaded |
| Complete system | ~2 GB | Running |

---

## 🐛 Troubleshooting

### Docker not installed
```bash
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
```

### Permission denied
```bash
sudo usermod -aG docker $USER
# Log out and back in
```

### Port 3000 in use
```bash
# Change in .env or docker-compose.yml
API_PORT=3001
```

### Slow startup
```bash
# Check container status
docker-compose logs -f
# Wait 30-60 seconds for services to initialize
```

---

## 📚 Documentation

All documentation is included:

- **README.md** - Project overview
- **QUICKSTART.md** - Quick setup guide
- **ARCHITECTURE.md** - System design
- **SETUP-VBOX.md** - VirtualBox instructions
- **IMPLEMENTATION_SUMMARY.md** - Feature list

---

## 🔗 Repository

- **GitHub:** https://github.com/netanelcyber/HOSPITAL
- **Branch:** `claude/distributed-sharepoint-system-kim830`
- **Status:** ✅ Complete and ready

---

## 📞 Support

For issues:
1. Check documentation in `/docs`
2. Review `docker-compose logs`
3. Check system requirements
4. Review GitHub issues

---

**Version:** 1.0.0  
**Last Updated:** 2024-07-30  
**Status:** ✅ Production Ready
