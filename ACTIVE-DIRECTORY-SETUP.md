# Active Directory Integration Guide

## Overview

The Distributed SharePoint System now includes integrated Active Directory (LDAP) support for enterprise authentication. This guide explains how to configure and use Active Directory for user authentication and group management.

---

## 🔧 Configuration

### Environment Variables

Add the following to your `.env` file to enable Active Directory:

```bash
# Active Directory Configuration
AD_ENABLED=true
AD_SERVER_URL=ldap://ad.example.com:389
AD_BASE_DN=dc=example,dc=com
AD_BIND_DN=cn=admin,dc=example,dc=com
AD_BIND_PASSWORD=your-admin-password
AD_USER_SEARCH_BASE=ou=users,dc=example,dc=com
AD_GROUP_SEARCH_BASE=ou=groups,dc=example,dc=com
AD_TLS_ENABLED=true
AD_TLS_CERT_PATH=/etc/ssl/certs/ca-bundle.crt
AD_SYNC_INTERVAL=3600000
AD_ALLOW_LOCAL_FALLBACK=true
```

### Configuration Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `AD_ENABLED` | Enable/disable AD integration | `false` |
| `AD_SERVER_URL` | LDAP server URL | Required when enabled |
| `AD_BASE_DN` | Base Distinguished Name | Required |
| `AD_BIND_DN` | Admin account DN for binding | Required |
| `AD_BIND_PASSWORD` | Admin password | Required |
| `AD_USER_SEARCH_BASE` | OU containing users | Required |
| `AD_GROUP_SEARCH_BASE` | OU containing groups | Required |
| `AD_TLS_ENABLED` | Use TLS/SSL | `true` |
| `AD_TLS_CERT_PATH` | Path to CA certificate | Optional |
| `AD_SYNC_INTERVAL` | Auto-sync interval (ms) | `3600000` (1 hour) |
| `AD_ALLOW_LOCAL_FALLBACK` | Fall back to local DB auth | `true` |

---

## 🚀 Authentication Flow

### Login Endpoint: `POST /api/v1/auth/login`

```bash
curl -X POST http://localhost:3000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "jdoe",
    "password": "password123"
  }'
```

**Response:**
```json
{
  "user": {
    "id": "uuid",
    "username": "jdoe",
    "email": "jdoe@example.com",
    "role": "doctor",
    "source": "active_directory"
  },
  "token": "eyJhbGc..."
}
```

### Authentication Priority

1. **Active Directory** (if enabled and AD_ALLOW_LOCAL_FALLBACK=true)
   - Authenticates against AD server
   - Syncs user data to local database
   - Maps AD groups to DSS roles
   
2. **Local Database** (fallback)
   - Uses bcrypt password verification
   - Uses local role assignment
   - Falls back if AD authentication fails

---

## 👥 User Synchronization

When a user authenticates via Active Directory:

1. System attempts to authenticate against AD
2. If successful, user data is synced to local database:
   - Username
   - Email
   - Full name
   - Department
   - Groups

3. User roles are determined by:
   - Group membership in AD
   - Group-to-role mapping configured in AD

4. User status is marked as "active" in local database

### User Sync Endpoints

#### Check AD Status
```bash
curl http://localhost:3000/api/v1/auth/ad/status \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "enabled": true,
  "connected": true,
  "serverUrl": "ldap://ad.example.com:389",
  "baseDN": "dc=example,dc=com",
  "cachedUsers": 125,
  "cachedGroups": 34,
  "syncInterval": 3600000,
  "isSyncing": true
}
```

#### Get User's AD Groups
```bash
curl http://localhost:3000/api/v1/auth/ad/groups/jdoe \
  -H "Authorization: Bearer $TOKEN"
```

**Response:**
```json
{
  "username": "jdoe",
  "groups": [
    "Domain Users",
    "Hospital Staff",
    "Doctors"
  ]
}
```

---

## 🔐 Group-to-Role Mapping

Configure AD group to DSS role mappings in your Active Directory module initialization:

```typescript
const adConfig = {
  groupMapping: {
    "Hospital Admins": "admin",
    "Doctors": "doctor",
    "Nurses": "clinician",
    "Administrative Staff": "user",
    "Viewers": "viewer",
  }
};
```

### Default Roles

- **admin** - Full system access
- **doctor** - PHI access, can create/modify documents
- **clinician** - PHI access, limited modification
- **user** - Standard user access
- **viewer** - Read-only access

---

## 🔒 Security Features

### Password Management

- Passwords stored in Active Directory only
- Local database does not store AD passwords
- Password expiry enforced by AD policies

### Session Management

- JWT tokens expire after 24 hours (configurable)
- Session timeout: 30 minutes
- MFA capability available through AD

### Audit Logging

All AD authentication attempts are logged:
- Timestamp
- Username
- Result (success/failure)
- IP address
- Duration

View audit logs:
```bash
curl http://localhost:3000/api/v1/compliance/audit-logs \
  -H "Authorization: Bearer $TOKEN"
```

---

## 🌐 Hybrid Authentication

The system supports both AD and local database authentication:

### Configuration for Hybrid Mode

```bash
AD_ENABLED=true
AD_ALLOW_LOCAL_FALLBACK=true
```

**Benefits:**
- AD users authenticate via LDAP
- Local users (non-AD) authenticate via database
- Fallback if AD is unavailable
- Service accounts can use local auth

### Configuration for AD-Only

```bash
AD_ENABLED=true
AD_ALLOW_LOCAL_FALLBACK=false
```

If AD is unavailable, login fails. No local fallback.

---

## 📋 Setup Steps

### Step 1: Prepare Active Directory

1. Identify AD server details:
   - Server hostname/IP
   - LDAP port (usually 389 or 636)
   - Base DN (e.g., dc=example,dc=com)

2. Create service account:
   ```
   Username: ad-dss-service
   Password: secure-password
   Permissions: Read users and groups
   ```

3. Create user search OU:
   ```
   OU=DSS Users
   OU=Users
   DC=example
   DC=com
   ```

4. Create group mapping:
   ```
   DSS-Admins -> admin role
   DSS-Doctors -> doctor role
   DSS-Staff -> user role
   ```

### Step 2: Configure Environment

Update `.env` with AD details:

```bash
AD_ENABLED=true
AD_SERVER_URL=ldap://ad.example.com:389
AD_BASE_DN=dc=example,dc=com
AD_BIND_DN=cn=ad-dss-service,cn=users,dc=example,dc=com
AD_BIND_PASSWORD=secure-password
AD_USER_SEARCH_BASE=ou=dss-users,ou=users,dc=example,dc=com
AD_GROUP_SEARCH_BASE=ou=dss-groups,dc=example,dc=com
AD_TLS_ENABLED=false
AD_ALLOW_LOCAL_FALLBACK=true
```

### Step 3: Test Connection

```bash
# Restart application
docker-compose restart dss-api

# Check logs for AD connection
docker-compose logs dss-api | grep "Active Directory"

# Test AD status endpoint
curl http://localhost:3000/api/v1/auth/ad/status
```

### Step 4: Test Authentication

```bash
# Test login with AD user
curl -X POST http://localhost:3000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "aduser",
    "password": "adpassword"
  }'
```

---

## 🐛 Troubleshooting

### Connection Issues

**Error: "Failed to connect to AD server"**

```bash
# Check network connectivity to AD server
telnet ad.example.com 389

# Verify LDAP configuration
ldapsearch -x -H ldap://ad.example.com:389 -b "dc=example,dc=com" -w password
```

**Error: "Bind failed"**

```bash
# Verify bind credentials
# Check AD user exists and has proper permissions
# Verify DN format: cn=user,dc=example,dc=com
```

### User Search Issues

**Error: "User not found in AD"**

```bash
# Verify user search base
# Check user exists in configured OU
# Verify search base DN is correct
```

**Error: "Group mapping failed"**

```bash
# Check group names match exactly (case-sensitive)
# Verify groups exist in configured OU
# Check group membership for user
```

### Performance Issues

**Slow login with AD:**

1. Check network latency to AD server
2. Verify AD server performance
3. Increase cache size (adService.userCache)
4. Reduce sync interval

---

## 📊 Monitoring

### Check AD Service Status

```bash
curl http://localhost:3000/api/v1/auth/ad/status
```

### View Cache Statistics

```bash
# From AD status endpoint
{
  "cachedUsers": 125,      # Number of cached users
  "cachedGroups": 34,      # Number of cached groups
  "isSyncing": true        # Sync in progress
}
```

### Monitor Sync Activity

```bash
# Watch application logs
docker-compose logs -f dss-api | grep "AD sync"
```

---

## 🔄 Integration with DNS

For complete PENUX.UK domain integration with Active Directory:

1. **AD Server Setup:**
   ```
   AD Server: ad.penux.uk
   LDAP Port: 389 (or 636 for TLS)
   ```

2. **Environment Configuration:**
   ```bash
   AD_SERVER_URL=ldap://ad.penux.uk:389
   DOMAIN=api.penux.uk
   ALLOWED_ORIGINS=https://api.penux.uk,https://www.penux.uk
   ```

3. **DNS SRV Records:**
   ```
   _ldap._tcp.penux.uk  SRV  0 100 389 ad.penux.uk
   _ldaps._tcp.penux.uk SRV  0 100 636 ad.penux.uk
   ```

4. **Verify Configuration:**
   ```bash
   # Check AD resolution
   nslookup ad.penux.uk
   
   # Test LDAP connectivity
   telnet ad.penux.uk 389
   ```

---

## 📚 Reference

### Active Directory Module

**File:** `src/enterprise/active-directory.ts`

**Key Classes:**
- `ActiveDirectoryService` - Main AD integration class
- `ADConfig` - Configuration interface
- `ADUser` - User object from AD
- `ADGroup` - Group object from AD

### Authentication API

**File:** `src/api/auth.ts`

**Endpoints:**
- `POST /auth/register` - Local user registration
- `POST /auth/login` - Login (AD or local)
- `POST /auth/refresh` - Refresh JWT token
- `GET /auth/ad/status` - AD service status
- `GET /auth/ad/groups/:username` - User's AD groups

---

## ✅ Checklist

- [ ] Active Directory server identified
- [ ] Service account created in AD
- [ ] User and group OUs configured
- [ ] Group-to-role mapping defined
- [ ] `.env` updated with AD settings
- [ ] Network connectivity verified (telnet test)
- [ ] AD connection tested
- [ ] User authentication tested
- [ ] Group mapping verified
- [ ] Audit logging working
- [ ] Fallback authentication tested (if enabled)
- [ ] Performance acceptable (<1s login)
- [ ] DNS SRV records created (optional)
- [ ] TLS certificate configured (if using LDAPS)

---

## 🔗 Related Documentation

- **DNS Configuration:** [DNS-CONFIG.md](DNS-CONFIG.md)
- **HIPAA Compliance:** [RELEASES.md](RELEASES.md#-security-features)
- **API Gateway Security:** [ARCHITECTURE.md](ARCHITECTURE.md#security--compliance)
- **Network Segmentation:** [ARCHITECTURE.md](ARCHITECTURE.md#network-segmentation-4-vlans)

---

**Document Version:** 1.0  
**Last Updated:** July 30, 2024  
**Status:** Production Ready
