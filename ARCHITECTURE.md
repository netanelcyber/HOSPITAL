# Distributed SharePoint System - Architecture Documentation

## Overview

The Distributed SharePoint System (DSS) is a cloud-based document management and collaboration platform with medical imaging support (PACS), healthcare data interoperability (FHIR), and advanced Unix-based notification infrastructure.

## System Components

### 1. Core API Server (Node.js/Express)
- RESTful API with JWT authentication
- Document management with nested folder support
- PACS (medical imaging) support
- Optional FHIR healthcare data support
- Real-time notifications via WebSocket and Unix sockets
- VM orchestration for nested virtualization

### 2. Data Layer

#### PostgreSQL (Relational Database)
- User management
- Document metadata
- Document versions and history
- Access logs and audit trails
- PACS studies, series, and instances
- Share/permission information
- Notification queue

#### Redis (Cache Layer)
- Session caching
- Document tree caching
- Real-time data structures
- Queue management

#### S3-Compatible Storage (MinIO)
- Document file storage
- DICOM image storage
- Version history
- Distributed replication

### 3. Notification System (Unix-Based)

#### Signal Handlers (UNIX Signals)
- SIGUSR1: Process notification queue
- SIGUSR2: Health check ping
- SIGTERM: Graceful shutdown

#### Unix Domain Sockets
- Real-time client connections
- Low-latency event delivery
- Automatic cleanup on disconnect

#### FIFO Queues (Named Pipes)
- Asynchronous message delivery
- External process integration
- Robust message persistence

### 4. VM Orchestration Layer

#### VirtualBox Support
- Full VM lifecycle management
- Nested VM creation
- Resource allocation (CPU, memory, disk)

#### KVM/QEMU Support
- Linux KVM hypervisor support
- QEMU integration
- Better performance on Linux

#### Docker Support
- Container-based VMs
- Lightweight nested containers
- Development environment

### 5. Medical Systems

#### PACS (Picture Archiving and Communication System)
- DICOM file storage and retrieval
- Study/Series/Instance hierarchy
- Medical image metadata
- Distributed storage with replication

#### FHIR (Optional)
- HL7 FHIR R4 support
- Patient resources
- Observation resources
- Condition resources
- Healthcare data interoperability

## Data Flow Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Client Applications                     │
│  (Web UI, Mobile, Desktop, External Systems, DICOM Tools)   │
└──────────────────────┬──────────────────────────────────────┘
                       │
                       │ HTTPS
                       │
        ┌──────────────▼─────────────────┐
        │     API Server (Node.js)        │
        │  ├─ Auth & Authorization       │
        │  ├─ Document Management        │
        │  ├─ PACS Service               │
        │  ├─ FHIR Endpoints             │
        │  └─ VM Orchestration           │
        └──┬─────────────┬──────────┬─────┘
           │             │          │
    ┌──────▼──┐  ┌──────▼──┐  ┌───▼──────┐
    │PostgreSQL │  │ Redis   │  │ MinIO   │
    │ Metadata  │  │ Cache   │  │Storage  │
    │ & Logs    │  │ & Queue │  │& DICOM  │
    └───────────┘  └─────────┘  └─────────┘
           ▲
           │
    ┌──────┴──────────────────┐
    │  Unix Notification Bus   │
    │ (Sockets, FIFO, Signals) │
    └──────────────────────────┘
```

## Authentication & Authorization

### JWT (JSON Web Tokens)
- Claims: user_id, username, email, role
- Expiration: 24 hours (configurable)
- Refresh token support

### Role-Based Access Control (RBAC)
- Roles: admin, user, viewer, editor
- Document-level permissions
- Share-based access control

## Distributed Storage Strategy

### Replication Strategies

1. **Full Replication**
   - All data replicated to all nodes
   - Highest redundancy
   - Higher bandwidth usage

2. **Sharded Replication**
   - Data divided across nodes
   - Reduced storage per node
   - Consistency protocol required

3. **Cached Replication**
   - Hot data cached, cold data retrieved
   - Intelligent prefetching
   - Best for variable access patterns

### Node Architecture

```
Storage Node 1 ←──→ Replication ←──→ Storage Node 2
     ↓                                      ↓
  RAID Arrays                          RAID Arrays
  + Backup                             + Backup
```

## UNIX Notification System Details

### Socket-Based Communication
```bash
# Client subscribes to notifications
echo '{"action":"subscribe","userId":"abc","eventTypes":["document_uploaded"]}' | nc -U /tmp/dss-notification.sock
```

### Signal-Based Processing
- SIGUSR1 triggers queue processing
- Used for inter-process coordination
- External monitoring integration

### FIFO Queue
- Named pipe at `/tmp/dss-notification-queue`
- External processes can write events
- Automatic distribution to subscribers

## Nested VM Support

### Hierarchy
```
Base VM (VirtualBox)
  ├── Nested VM 1 (Docker)
  │   ├── Application Container
  │   └── Database Container
  └── Nested VM 2 (Docker)
      └── Test Environment
```

### Resource Allocation
- CPU: Guaranteed allocation with sharing
- Memory: Configurable limits per VM
- Disk: Separate volumes per VM
- Network: Internal bridges + NAT

## PACS Integration

### DICOM Handling
- Receive DICOM files via HTTP
- Store in distributed storage
- Maintain metadata index
- Query studies/series/instances

### Study Hierarchy
```
Study (Patient-Level)
  └── Series (Imaging Series)
      └── Instance (Individual Image)
          └── DICOM File
```

## FHIR Integration (Optional)

### Supported Resources
- Patient: Demographic information
- Observation: Medical measurements
- Condition: Diagnoses and conditions
- MedicationStatement: Medication history

### Capabilities Statement
- Describes server capabilities
- Lists supported resources
- Defines interaction types

## Security

### Data Protection
- Encrypted at rest (S3 server-side encryption)
- Encrypted in transit (HTTPS/TLS)
- Database encryption available

### Access Control
- JWT-based authentication
- Role-based authorization
- Share links with expiration
- Audit logging of all access

### Network Security
- Firewall rules for API
- Isolated Docker networks
- No external database access
- Unix socket local-only access

## Performance Considerations

### Caching Strategy
- Document tree cached for 10 minutes
- User session data cached
- PACS metadata indexed

### Database Optimization
- Indexes on frequently queried columns
- Connection pooling (20 concurrent)
- Read replicas for reports

### Storage Optimization
- Compression for archival
- Deduplication via checksums
- Lazy loading of documents

## Deployment Models

### 1. Docker Compose (Development)
- Single machine deployment
- All services in containers
- Shared volumes for data

### 2. Kubernetes (Production)
- Horizontal scaling
- Auto-recovery
- Load balancing
- Rolling updates

### 3. VirtualBox ISO (Testing)
- Complete standalone system
- Pre-configured
- Network-isolated
- Reproducible testing

## Monitoring & Logging

### Logging Strategy
- Application logs (Pino)
- Database audit logs
- Access logs for all file operations
- Notification processing logs

### Health Checks
- HTTP health endpoint
- Database connectivity
- Storage availability
- Cache cluster status

## Failure Handling

### Data Loss Prevention
- Write-ahead logging (PostgreSQL)
- S3 versioning enabled
- Backup retention (configurable)
- Point-in-time recovery

### Service Recovery
- Automatic service restart
- Health check-based recovery
- Graceful degradation
- Circuit breaker patterns

## Scaling Architecture

### Horizontal Scaling
- Stateless API servers (can add more)
- Shared database (connection pooling)
- Shared storage (S3)
- Shared cache (Redis cluster)

### Vertical Scaling
- Increase CPU/memory for services
- Database tuning
- Storage optimization

## Future Enhancements

- [ ] Full-text search (Elasticsearch)
- [ ] Real-time collaborative editing
- [ ] GraphQL API
- [ ] Mobile app
- [ ] Machine learning pipeline
- [ ] Advanced PACS features (3D rendering)
- [ ] HIPAA compliance module
- [ ] Multi-tenancy support
