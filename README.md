# Distributed SharePoint System (DSS)

A cloud-based distributed document management and collaboration system built with a UNIX-based notification infrastructure.

## Features

- **Distributed Document Storage**: Cloud-agnostic file storage across multiple nodes
- **Real-time Collaboration**: Live editing and notifications
- **Access Control**: Role-based permissions and sharing
- **Version Control**: Document versioning and history
- **UNIX Notification System**: Signal-based, queue-based, and socket-based notifications
- **Metadata Replication**: Consistent metadata across distributed nodes
- **API & WebUI**: REST API and web interface for document management

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Web Client / Desktop                  │
└────────────┬────────────────────────────────────────────┘
             │
┌────────────┴────────────────────────────────────────────┐
│              API Server (Node.js/Express)                │
│  ├─ Document Endpoints                                  │
│  ├─ Permission Endpoints                                │
│  ├─ Sharing Endpoints                                   │
│  └─ Notification Subscriptions                          │
└────────────┬───────────────────────────┬────────────────┘
             │                           │
    ┌────────▼────────┐         ┌────────▼──────────┐
    │  Metadata DB    │         │ UNIX Notification │
    │  (PostgreSQL)   │         │     Service       │
    │  Replication    │         │  ├─ Signal Queue  │
    └────────┬────────┘         │  ├─ Unix Sockets  │
             │                  │  └─ Pipes & FIFOs │
             │                  └────────┬──────────┘
    ┌────────▼──────────────────────────┘
    │
┌───┴─────────────────────────────────────┐
│  Distributed Storage Layer              │
│  ├─ S3-compatible (MinIO)               │
│  ├─ Node Replication                    │
│  ├─ Sharding Strategy                   │
│  └─ Consistency Protocol                │
└─────────────────────────────────────────┘
```

## Technology Stack

- **Backend**: Node.js, Express.js
- **Database**: PostgreSQL (metadata), Redis (cache)
- **Storage**: S3-compatible object storage
- **Notifications**: UNIX signals, sockets, queues
- **Frontend**: React + TypeScript
- **IPC**: UNIX pipes, domain sockets, message queues

## Installation

```bash
npm install
npm run setup
npm start
```

## Configuration

See `config/` directory for environment-specific configurations.
