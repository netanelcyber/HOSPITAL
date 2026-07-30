# Distributed SharePoint System - Quick Start Guide

## Prerequisites

### For Development
- Node.js 18+
- npm or yarn
- Docker & Docker Compose
- PostgreSQL 15+ (or use Docker)
- Redis 7+ (or use Docker)

### For Production/Testing
- VirtualBox 7+ (for ISO testing)
- 4GB RAM minimum per VM
- 20GB disk space

## Installation & Setup

### 1. Quick Setup (Using Docker Compose)

```bash
# Clone the repository (already done)
cd /home/user/HOSPITAL

# Copy environment configuration
cp .env.example .env

# Build and start all services
docker-compose up -d

# Wait for services to initialize
sleep 30

# Check service health
curl http://localhost:3000/health
```

### 2. Manual Development Setup

```bash
# Install dependencies
npm install

# Build TypeScript
npm run build

# Setup environment
cp .env.example .env

# Start PostgreSQL (in another terminal)
docker run -d --name postgres -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:15

# Start Redis (in another terminal)
docker run -d --name redis -p 6379:6379 redis:7

# Run migrations
npm run migrate

# Start the API server
npm start
```

### 3. Development with Hot Reload

```bash
npm run dev
```

## Using the System

### Authentication

```bash
# Register a new user
curl -X POST http://localhost:3000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "email": "admin@hospital.local",
    "password": "secure-password",
    "fullName": "Admin User"
  }'

# Login
curl -X POST http://localhost:3000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "secure-password"
  }'

# Response includes:
# {
#   "user": { "id": "...", "username": "admin", "email": "...", "role": "user" },
#   "token": "eyJhbGciOiJIUzI1NiIs..."
# }
```

### Document Management

```bash
# Set your token
TOKEN="your-jwt-token-here"

# Create a folder
curl -X POST http://localhost:3000/api/v1/documents/folders \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "My Documents",
    "parentId": null
  }'

# Upload a document
curl -X POST http://localhost:3000/api/v1/documents/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@my-file.pdf" \
  -F "parentId=folder-uuid" \
  -F "description=My important document"

# Get document tree (nested structure)
curl -X GET http://localhost:3000/api/v1/documents/tree \
  -H "Authorization: Bearer $TOKEN"

# Download a document
curl -X GET http://localhost:3000/api/v1/documents/{documentId}/download \
  -H "Authorization: Bearer $TOKEN" \
  --output my-file.pdf
```

### PACS (Medical Imaging)

```bash
# Upload DICOM file
curl -X POST http://localhost:3000/api/v1/pacs/studies/upload \
  -H "Authorization: Bearer $TOKEN" \
  -F "dicom=@study.dcm" \
  -F "studyUid=1.2.3.4.5" \
  -F "patientId=PAT-001" \
  -F "patientName=John Doe" \
  -F "studyDate=2024-01-15" \
  -F "seriesUid=1.2.3.4.5.1" \
  -F "modality=CT"

# Get studies
curl -X GET "http://localhost:3000/api/v1/pacs/studies?patientId=PAT-001" \
  -H "Authorization: Bearer $TOKEN"

# Get PACS statistics
curl -X GET http://localhost:3000/api/v1/pacs/stats \
  -H "Authorization: Bearer $TOKEN"
```

### Document Sharing

```bash
# Share with another user
curl -X POST http://localhost:3000/api/v1/sharing/{documentId}/share \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "sharedWithId": "other-user-id",
    "permissionLevel": "view"
  }'

# Create public share link
curl -X POST http://localhost:3000/api/v1/sharing/{documentId}/public-share \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "permissionLevel": "download",
    "expiresAt": "2024-12-31T23:59:59Z"
  }'

# Access via public link (no auth required)
curl -X GET http://localhost:3000/api/v1/sharing/link/{shareLink}/download \
  --output shared-file.pdf
```

### FHIR Healthcare Data (Optional)

```bash
# Enable FHIR in .env
# FHIR_ENABLED=true

# Create a patient
curl -X POST http://localhost:3000/api/v1/fhir/Patient \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "John Doe",
    "identifier": "12345",
    "birthDate": "1990-01-15",
    "gender": "male"
  }'

# Create an observation
curl -X POST http://localhost:3000/api/v1/fhir/Observation \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "status": "final",
    "code": "55284-4",
    "value": "98.6",
    "effectiveDateTime": "2024-01-15T10:30:00Z"
  }'
```

### VM Orchestration

```bash
# Create a VM
curl -X POST http://localhost:3000/api/v1/vms \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "test-vm",
    "cpu": 2,
    "memory": 2048,
    "disk": 20,
    "hypervisor": "docker"
  }'

# List VMs
curl -X GET http://localhost:3000/api/v1/vms \
  -H "Authorization: Bearer $TOKEN"

# Start a VM
curl -X POST http://localhost:3000/api/v1/vms/{vmId}/start \
  -H "Authorization: Bearer $TOKEN"

# Create nested VM
curl -X POST http://localhost:3000/api/v1/vms/{vmId}/nested \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "nested-test",
    "cpu": 1,
    "memory": 1024,
    "disk": 10
  }'
```

### Real-time Notifications

```bash
# Subscribe to notifications
curl -X GET "http://localhost:3000/api/v1/notifications/subscribe?eventTypes=document_uploaded,document_shared" \
  -H "Authorization: Bearer $TOKEN"

# Via WebSocket (requires socket.io client)
# Connection to ws://localhost:3000/socket.io with auth token

# Get notification history
curl -X GET http://localhost:3000/api/v1/notifications/history \
  -H "Authorization: Bearer $TOKEN"

# Get notification stats
curl -X GET http://localhost:3000/api/v1/notifications/stats \
  -H "Authorization: Bearer $TOKEN"
```

## Building ISO for VirtualBox

### Prerequisites
- Ubuntu/Debian Linux
- `xorriso` or `mkisofs` package
- `wget` for downloading base ISO
- ~10GB free disk space

### Build Process

```bash
# Make the ISO build script executable
chmod +x scripts/create-standalone-iso.sh

# Build the complete ISO
bash scripts/create-standalone-iso.sh

# This will create: build/dss-complete.iso
```

### Testing ISO with VirtualBox

```bash
# Create VM from command line
VBoxManage createvm \
  --name "DSS-Hospital" \
  --ostype "Linux_64" \
  --register

# Configure VM
VBoxManage modifyvm "DSS-Hospital" \
  --cpus 4 \
  --memory 8192 \
  --nic1 bridged \
  --bridgeadapter1 eth0

# Attach ISO
VBoxManage storageattach "DSS-Hospital" \
  --storagectl SATA \
  --port 0 \
  --device 0 \
  --type dvddrive \
  --medium build/dss-complete.iso

# Start VM
VBoxManage startvm "DSS-Hospital" --type gui
```

## Common Commands

```bash
# Using Makefile
make help              # Show all commands
make setup             # Install and build
make dev               # Start development server
make docker-up         # Start Docker services
make docker-down       # Stop Docker services
make docker-logs       # View service logs
make iso               # Build ISO image
make clean             # Clean build artifacts
make db-shell          # Access PostgreSQL shell
make redis-cli         # Access Redis CLI
make health-check      # Check service health
```

## Troubleshooting

### Services won't start
```bash
# Check Docker status
docker ps
docker-compose ps

# View logs
docker-compose logs -f dss-api

# Restart services
docker-compose restart
```

### Database connection issues
```bash
# Check if PostgreSQL is running
docker-compose exec postgres psql -U postgres -l

# Reset database
make db-reset
```

### Port already in use
```bash
# Find what's using the port (e.g., 3000)
lsof -i :3000

# Kill the process (if needed)
kill -9 <PID>
```

### PACS issues
```bash
# Verify DICOM service is listening
netstat -tlnp | grep 11112

# Check PACS logs
docker-compose logs dss-api | grep PACS
```

## Next Steps

1. Read [ARCHITECTURE.md](./ARCHITECTURE.md) for system design details
2. Check [API Documentation](./docs/API.md) for endpoint references
3. Review [SECURITY.md](./docs/SECURITY.md) for security guidelines
4. Explore [examples/](./examples/) for integration examples

## Support

For issues or questions:
1. Check logs: `docker-compose logs -f`
2. Review GitHub issues
3. Check documentation in `/docs` directory
4. Report bugs with logs and reproduction steps

## License

This project is licensed under MIT License - see LICENSE file for details.
