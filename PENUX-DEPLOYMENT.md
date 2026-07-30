# PENUX.UK Complete Deployment Guide

## Overview

This guide provides step-by-step instructions for deploying the Distributed SharePoint System to the **penux.uk** domain with full Active Directory integration, DNS configuration, and SSL/TLS security.

---

## 🎯 Deployment Components

### 1. Domain Setup (penux.uk)
- DNS A records pointing to server IP
- CNAME records for subdomains
- SRV records for services (LDAP, DICOM)
- Let's Encrypt SSL certificates

### 2. Active Directory Integration
- LDAP authentication
- User and group synchronization
- Role-based access control
- Audit logging

### 3. Network Configuration
- Reverse proxy (Nginx/Apache)
- TLS/HTTPS enforcement
- Security headers
- Firewall rules

### 4. Application Services
- API Server on api.penux.uk
- Database (PostgreSQL)
- Cache (Redis)
- Storage (MinIO S3)

---

## 📋 Prerequisites

### Domain Requirements
- Domain: **penux.uk** (registered and manageable)
- Server IP: Static public IP address
- DNS provider with SRV record support

### Infrastructure Requirements
- OS: Linux (Ubuntu 20.04+)
- CPU: 4 cores minimum
- RAM: 8GB minimum
- Disk: 50GB minimum
- Docker & Docker Compose installed

### Active Directory Requirements
- AD server accessible from application server
- Service account with read permissions
- User and group OUs created
- Group-to-role mapping defined

---

## 🚀 Step-by-Step Deployment

### Step 1: DNS Configuration

#### 1.1 Add DNS Records

Contact your DNS provider and add these records:

**A Record (Primary)**
```
Name:  api.penux.uk
Type:  A
Value: YOUR_SERVER_IP
TTL:   3600
```

**AAAA Record (IPv6 - Optional)**
```
Name:  api.penux.uk
Type:  AAAA
Value: YOUR_IPV6_ADDRESS
TTL:   3600
```

**CNAME Records (Subdomains)**
```
Name:  www.penux.uk
Type:  CNAME
Value: api.penux.uk
TTL:   3600

Name:  mail.penux.uk
Type:  CNAME
Value: api.penux.uk
TTL:   3600
```

**SRV Records (Services)**
```
Name:     _ldap._tcp.penux.uk
Type:     SRV
Priority: 0
Weight:   100
Port:     389
Value:    ad.penux.uk
TTL:      3600

Name:     _ldaps._tcp.penux.uk
Type:     SRV
Priority: 0
Weight:   100
Port:     636
Value:    ad.penux.uk
TTL:      3600

Name:     _dicom._tcp.penux.uk
Type:     SRV
Priority: 0
Weight:   100
Port:     11112
Value:    api.penux.uk
TTL:      3600

Name:     _fhir._http._tcp.penux.uk
Type:     SRV
Priority: 10
Weight:   60
Port:     3000
Value:    api.penux.uk
TTL:      3600
```

#### 1.2 Verify DNS Propagation

```bash
# Check A record
nslookup api.penux.uk

# Check CNAME
nslookup www.penux.uk

# Check SRV records
nslookup -type=SRV _ldap._tcp.penux.uk

# Use dig for detailed info
dig api.penux.uk +short

# Check propagation globally
# Use online tool: https://mxtoolbox.com/
```

**Expected output:**
```
api.penux.uk has address 1.2.3.4
www.penux.uk canonical name = api.penux.uk
```

### Step 2: SSL Certificate Setup

#### 2.1 Obtain Let's Encrypt Certificate

```bash
# Install Certbot
sudo apt-get update
sudo apt-get install certbot certbot-nginx certbot-apache

# Generate certificate
sudo certbot certonly --standalone \
  -d api.penux.uk \
  -d www.penux.uk \
  -d penux.uk

# Verify certificate
sudo ls -la /etc/letsencrypt/live/api.penux.uk/

# Check expiration
echo | openssl s_client -servername api.penux.uk -connect api.penux.uk:443 2>/dev/null | \
  openssl x509 -noout -dates
```

#### 2.2 Setup Certificate Renewal

```bash
# Enable automatic renewal
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer

# Verify renewal scheduled
sudo systemctl list-timers certbot.timer

# Test renewal dry-run
sudo certbot renew --dry-run
```

### Step 3: Configure Reverse Proxy

#### 3.1 Nginx Configuration

Create `/etc/nginx/sites-available/penux-uk`:

```nginx
# Redirect HTTP to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name api.penux.uk www.penux.uk penux.uk;

    return 301 https://$server_name$request_uri;
}

# HTTPS Server
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name api.penux.uk www.penux.uk penux.uk;

    # SSL Certificates
    ssl_certificate /etc/letsencrypt/live/api.penux.uk/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.penux.uk/privkey.pem;

    # SSL Configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Security Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;

    # Logging
    access_log /var/log/nginx/penux-access.log;
    error_log /var/log/nginx/penux-error.log;

    # API Proxy
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $server_name;
        
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # FHIR API
    location /api/v1/fhir {
        proxy_pass http://localhost:3000/api/v1/fhir;
        add_header Content-Type "application/fhir+json";
        
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # PACS/DICOM
    location /pacs {
        proxy_pass http://localhost:11112;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/penux-uk /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

### Step 4: Application Configuration

#### 4.1 Update Environment Variables

Create/update `.env` file:

```bash
# Server
PORT=3000
NODE_ENV=production

# Database
DB_HOST=postgres
DB_PORT=5432
DB_USER=postgres
DB_PASSWORD=secure-password-here
DB_NAME=dss

# Redis
REDIS_HOST=redis
REDIS_PORT=6379

# Storage
STORAGE_TYPE=s3
S3_ENDPOINT=http://minio:9000
S3_ACCESS_KEY=minioadmin
S3_SECRET_KEY=minioadmin
S3_BUCKET=dss-storage

# JWT
JWT_SECRET=your-super-secure-jwt-secret-key-2024
JWT_EXPIRES_IN=24h

# PACS
PACS_ENABLED=true
DICOM_PORT=11112
DICOM_AET=PENUX_HOSPITAL

# FHIR
FHIR_ENABLED=true
FHIR_BASE_URL=https://api.penux.uk/api/v1/fhir

# Domain/DNS
DOMAIN=api.penux.uk
DOMAIN_SSL=true
DOMAIN_PORT=443
ALLOWED_ORIGINS=https://api.penux.uk,https://www.penux.uk,https://penux.uk
SSL_CERT_PATH=/etc/letsencrypt/live/api.penux.uk/fullchain.pem
SSL_KEY_PATH=/etc/letsencrypt/live/api.penux.uk/privkey.pem

# Active Directory
AD_ENABLED=true
AD_SERVER_URL=ldap://ad.penux.uk:389
AD_BASE_DN=dc=penux,dc=uk
AD_BIND_DN=cn=dss-service,cn=users,dc=penux,dc=uk
AD_BIND_PASSWORD=service-account-password
AD_USER_SEARCH_BASE=ou=hospital-users,dc=penux,dc=uk
AD_GROUP_SEARCH_BASE=ou=hospital-groups,dc=penux,dc=uk
AD_TLS_ENABLED=false
AD_SYNC_INTERVAL=3600000
AD_ALLOW_LOCAL_FALLBACK=true
```

#### 4.2 Update Docker Compose

Update `docker-compose.yml`:

```yaml
version: '3.8'

services:
  dss-api:
    build: .
    ports:
      - "3000:3000"
      - "11112:11112"
    environment:
      - NODE_ENV=production
      - PORT=3000
      - DB_HOST=postgres
      - DB_PORT=5432
      - DB_USER=postgres
      - DB_PASSWORD=${DB_PASSWORD}
      - DB_NAME=dss
      - REDIS_HOST=redis
      - REDIS_PORT=6379
      - S3_ENDPOINT=http://minio:9000
      - S3_ACCESS_KEY=${S3_ACCESS_KEY}
      - S3_SECRET_KEY=${S3_SECRET_KEY}
      - JWT_SECRET=${JWT_SECRET}
      - DOMAIN=${DOMAIN}
      - ALLOWED_ORIGINS=${ALLOWED_ORIGINS}
      - AD_ENABLED=${AD_ENABLED}
      - AD_SERVER_URL=${AD_SERVER_URL}
      - AD_BASE_DN=${AD_BASE_DN}
      - AD_BIND_DN=${AD_BIND_DN}
      - AD_BIND_PASSWORD=${AD_BIND_PASSWORD}
      - AD_USER_SEARCH_BASE=${AD_USER_SEARCH_BASE}
      - AD_GROUP_SEARCH_BASE=${AD_GROUP_SEARCH_BASE}
    depends_on:
      - postgres
      - redis
      - minio
    volumes:
      - ./logs:/app/logs
      - /etc/letsencrypt:/etc/letsencrypt:ro
    networks:
      - dss-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
      interval: 30s
      timeout: 10s
      retries: 3

  postgres:
    image: postgres:15-alpine
    environment:
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=${DB_PASSWORD}
      - POSTGRES_DB=dss
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - dss-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    networks:
      - dss-network
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  minio:
    image: minio/minio:latest
    environment:
      - MINIO_ROOT_USER=${S3_ACCESS_KEY}
      - MINIO_ROOT_PASSWORD=${S3_SECRET_KEY}
    command: server /data
    volumes:
      - minio_data:/data
    ports:
      - "9000:9000"
      - "9001:9001"
    networks:
      - dss-network
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3

volumes:
  postgres_data:
  redis_data:
  minio_data:

networks:
  dss-network:
    driver: bridge
```

### Step 5: Firewall Configuration

```bash
# Allow HTTPS
sudo ufw allow 443/tcp

# Allow HTTP (for redirect)
sudo ufw allow 80/tcp

# Allow DICOM/PACS
sudo ufw allow 11112/tcp

# Allow SSH
sudo ufw allow 22/tcp

# Enable firewall
sudo ufw enable

# Verify rules
sudo ufw status
```

### Step 6: Deployment

```bash
# Pull latest code
git clone https://github.com/netanelcyber/HOSPITAL.git
cd HOSPITAL
git checkout claude/distributed-sharepoint-system-kim830

# Copy .env file
cp .env.example .env
# Edit .env with your production values

# Build and start services
docker-compose up -d

# Check service health
docker-compose ps
docker-compose logs -f dss-api

# Verify containers are running
docker-compose exec dss-api curl http://localhost:3000/health
```

### Step 7: Verification

#### 7.1 DNS Resolution

```bash
# Test DNS
nslookup api.penux.uk
dig api.penux.uk +short

# Should return server IP
# Example output:
# api.penux.uk.   3600    IN  A   1.2.3.4
```

#### 7.2 SSL Certificate

```bash
# Check certificate
openssl s_client -connect api.penux.uk:443 -servername api.penux.uk

# Verify certificate chain
curl -v https://api.penux.uk/health 2>&1 | grep -i certificate

# Check expiration
echo | openssl s_client -servername api.penux.uk -connect api.penux.uk:443 2>/dev/null | \
  openssl x509 -noout -dates
```

#### 7.3 API Connectivity

```bash
# Basic connectivity
curl https://api.penux.uk/health

# With verbose output
curl -v https://api.penux.uk/health

# Check security headers
curl -I https://api.penux.uk/health
# Should include HSTS, CSP, X-Frame-Options

# API status
curl https://api.penux.uk/api/v1/status | jq .
```

#### 7.4 Active Directory

```bash
# Check AD status
curl https://api.penux.uk/api/v1/auth/ad/status

# Test login
curl -X POST https://api.penux.uk/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "testuser", "password": "testpass"}'
```

#### 7.5 FHIR API

```bash
# Check FHIR capability
curl https://api.penux.uk/api/v1/fhir/metadata | jq .

# Test patient resource
curl https://api.penux.uk/api/v1/fhir/Patient | jq .
```

#### 7.6 PACS/DICOM

```bash
# Check DICOM port
telnet api.penux.uk 11112

# DICOM tools (if installed)
dcmtk-echoscu api.penux.uk 11112 -aec PENUX_HOSPITAL
```

---

## 📊 Health Check Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Basic health check |
| `GET /api/v1/status` | API status |
| `GET /security/status` | Security layer status |
| `GET /api/v1/auth/ad/status` | Active Directory status |
| `GET /api/v1/fhir/metadata` | FHIR capability statement |

---

## 🔒 Post-Deployment Security

### 1. Enable HTTPS Redirect
✅ Configured in Nginx (HTTP → HTTPS)

### 2. Enable HSTS
✅ Configured with 1-year max-age

### 3. Configure CSP Headers
✅ Configured in API Gateway

### 4. Rate Limiting
✅ 100 requests per 15 minutes (API Gateway)

### 5. DDoS Protection
✅ IP-based rate limiting enabled

### 6. Audit Logging
✅ HIPAA-compliant 6-year retention

### 7. Active Directory MFA
- Configure in AD policies
- Requires MFA for sensitive operations

---

## 📈 Monitoring

### Container Logs

```bash
# API logs
docker-compose logs -f dss-api

# Database logs
docker-compose logs -f postgres

# All logs
docker-compose logs -f
```

### System Monitoring

```bash
# Check disk space
df -h

# Check memory
free -h

# Docker stats
docker stats
```

### Application Monitoring

```bash
# Security status
curl https://api.penux.uk/security/status

# AD sync status
curl https://api.penux.uk/api/v1/auth/ad/status

# Compliance report
curl https://api.penux.uk/api/v1/compliance/report
```

---

## 🔄 Maintenance

### Certificate Renewal

```bash
# Manual renewal (usually automatic)
sudo certbot renew --force-renewal

# Check renewal status
sudo systemctl status certbot.timer
```

### Backup

```bash
# Backup database
docker-compose exec postgres pg_dump -U postgres dss > backup-$(date +%Y%m%d).sql

# Backup certificates
sudo tar -czf ssl-backup-$(date +%Y%m%d).tar.gz \
  /etc/letsencrypt/

# Backup MinIO storage
docker-compose exec minio mc mirror minio/dss-storage ./backup/minio/
```

### Updates

```bash
# Pull latest code
git pull origin claude/distributed-sharepoint-system-kim830

# Rebuild containers
docker-compose build --no-cache

# Restart services
docker-compose down
docker-compose up -d
```

---

## 🆘 Troubleshooting

### DNS Not Resolving

```bash
# Check with different DNS servers
nslookup api.penux.uk 8.8.8.8
nslookup api.penux.uk 1.1.1.1

# Flush DNS cache
sudo systemd-resolve --flush-caches

# Check locally registered
cat /etc/hosts
```

### SSL Certificate Errors

```bash
# Verify certificate validity
curl -v https://api.penux.uk/ 2>&1 | grep certificate

# Check if certificate matches domain
openssl x509 -in /etc/letsencrypt/live/api.penux.uk/fullchain.pem \
  -noout -text | grep DNS

# Renew certificate
sudo certbot renew --force-renewal
```

### Active Directory Connection Issues

```bash
# Test LDAP connectivity
telnet ad.penux.uk 389

# Check LDAP config
ldapsearch -x -H ldap://ad.penux.uk:389 \
  -D "cn=dss-service,cn=users,dc=penux,dc=uk" \
  -w "password" \
  -b "dc=penux,dc=uk" \
  "(uid=testuser)"

# Check application logs
docker-compose logs dss-api | grep -i "active directory"
```

---

## ✅ Deployment Checklist

- [ ] Domain (penux.uk) registered and manageable
- [ ] Static IP assigned to server
- [ ] DNS A records added and propagating
- [ ] CNAME and SRV records configured
- [ ] SSL certificate obtained (Let's Encrypt)
- [ ] Certificate renewal automated
- [ ] Nginx/Apache reverse proxy configured
- [ ] Security headers enabled
- [ ] Firewall rules configured
- [ ] Environment variables configured
- [ ] Docker Compose file updated
- [ ] Active Directory configured and tested
- [ ] Application services deployed
- [ ] Health endpoints responding
- [ ] SSL certificate verified
- [ ] AD authentication tested
- [ ] FHIR API working
- [ ] PACS/DICOM accessible
- [ ] Monitoring and logging set up
- [ ] Backup strategy implemented
- [ ] Documentation updated

---

## 🔗 Related Documentation

- [DNS Configuration Guide](DNS-CONFIG.md)
- [Active Directory Setup](ACTIVE-DIRECTORY-SETUP.md)
- [Architecture Documentation](ARCHITECTURE.md)
- [Quick Start Guide](QUICKSTART.md)

---

**Document Version:** 1.0  
**Last Updated:** July 30, 2024  
**Status:** Production Ready  
**Domain:** penux.uk  
**Support:** GitHub Issues
