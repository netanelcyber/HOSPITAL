# DNS Configuration - PENUX.UK

## 🌐 Domain Setup for PENUX.UK

This guide explains how to configure your Distributed SharePoint System to use the custom domain **penux.uk**

---

## 📝 DNS Records Required

### Add these records to your DNS provider:

#### A Record (IPv4)
```
Type:    A
Name:    api.penux.uk (or @ for root)
Value:   YOUR_SERVER_IP
TTL:     3600
```

#### AAAA Record (IPv6) - Optional
```
Type:    AAAA
Name:    api.penux.uk
Value:   YOUR_IPV6_ADDRESS
TTL:     3600
```

#### CNAME Records (Subdomains)
```
Type:    CNAME
Name:    www.penux.uk
Value:   api.penux.uk
TTL:     3600
```

#### SRV Records (Services)
```
Type:    SRV
Name:    _pacs._tcp.penux.uk
Value:   10 60 11112 api.penux.uk
TTL:     3600

Type:    SRV
Name:    _fhir._tcp.penux.uk
Value:   10 60 3000 api.penux.uk
TTL:     3600
```

---

## 🔧 Configuration Files

### 1. Docker Compose with Domain

Edit `docker-compose.yml`:

```yaml
services:
  dss-api:
    environment:
      - DOMAIN=api.penux.uk
      - ALLOWED_ORIGINS=https://api.penux.uk,https://www.penux.uk
      - JWT_SECRET=your-secure-key-penux-uk
      - FHIR_BASE_URL=https://api.penux.uk/api/v1/fhir
```

### 2. Environment Configuration

Create `.env` with domain settings:

```bash
# Domain Configuration
DOMAIN=api.penux.uk
DOMAIN_SSL=true
DOMAIN_PORT=443

# API Server
API_HOST=0.0.0.0
API_PORT=3000

# Allowed Origins (CORS)
ALLOWED_ORIGINS=https://api.penux.uk,https://www.penux.uk,https://penux.uk

# Certificates (for SSL/TLS)
SSL_CERT_PATH=/etc/ssl/certs/penux.uk.crt
SSL_KEY_PATH=/etc/ssl/private/penux.uk.key

# FHIR Configuration
FHIR_BASE_URL=https://api.penux.uk/api/v1/fhir

# PACS Configuration
PACS_ENABLED=true
DICOM_AET=PENUX_HOSPITAL

# JWT
JWT_SECRET=penux-uk-secure-secret-key-2024
```

### 3. Nginx Reverse Proxy Configuration

If using Nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name api.penux.uk www.penux.uk penux.uk;

    # SSL Certificates
    ssl_certificate /etc/ssl/certs/penux.uk.crt;
    ssl_certificate_key /etc/ssl/private/penux.uk.key;

    # SSL Configuration
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    # Headers
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;

    # Reverse Proxy
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-Host $server_name;
    }

    # PACS DICOM
    location /pacs {
        proxy_pass http://localhost:11112;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }

    # FHIR API
    location /api/v1/fhir {
        proxy_pass http://localhost:3000/api/v1/fhir;
        add_header Content-Type "application/fhir+json";
    }
}

# HTTP Redirect
server {
    listen 80;
    server_name api.penux.uk www.penux.uk penux.uk;
    return 301 https://$server_name$request_uri;
}
```

### 4. Apache Configuration

If using Apache:

```apache
<VirtualHost *:443>
    ServerName api.penux.uk
    ServerAlias www.penux.uk penux.uk

    SSLEngine on
    SSLCertificateFile /etc/ssl/certs/penux.uk.crt
    SSLCertificateKeyFile /etc/ssl/private/penux.uk.key

    ProxyPreserveHost On
    ProxyPass / http://localhost:3000/
    ProxyPassReverse / http://localhost:3000/

    # PACS DICOM
    ProxyPass /pacs http://localhost:11112
    ProxyPassReverse /pacs http://localhost:11112

    # Headers
    Header always set Strict-Transport-Security "max-age=31536000; includeSubDomains"
    Header always set X-Content-Type-Options "nosniff"
    Header always set X-Frame-Options "DENY"
</VirtualHost>

<VirtualHost *:80>
    ServerName api.penux.uk
    ServerAlias www.penux.uk penux.uk
    Redirect permanent / https://api.penux.uk/
</VirtualHost>
```

---

## 🔐 SSL/TLS Certificates

### Option 1: Let's Encrypt (Recommended - Free)

```bash
# Install Certbot
sudo apt-get install certbot certbot-nginx

# Generate certificate
sudo certbot certonly --nginx -d api.penux.uk -d www.penux.uk -d penux.uk

# Auto-renewal
sudo systemctl enable certbot.timer
sudo systemctl start certbot.timer
```

### Option 2: Self-Signed (Testing Only)

```bash
# Generate self-signed certificate
openssl req -x509 -newkey rsa:4096 -keyout penux.uk.key \
  -out penux.uk.crt -days 365 -nodes \
  -subj "/CN=api.penux.uk"

# Copy to SSL directory
sudo cp penux.uk.crt /etc/ssl/certs/
sudo cp penux.uk.key /etc/ssl/private/
sudo chmod 644 /etc/ssl/certs/penux.uk.crt
sudo chmod 600 /etc/ssl/private/penux.uk.key
```

### Option 3: Purchased Certificate

```bash
# Place your certificates in:
# Certificate: /etc/ssl/certs/penux.uk.crt
# Private Key: /etc/ssl/private/penux.uk.key
# CA Bundle: /etc/ssl/certs/penux.uk.ca-bundle
```

---

## 🚀 Deployment Steps

### 1. Configure DNS
- Add A record pointing to your server IP
- Wait for DNS propagation (5-15 minutes)
- Test: `nslookup api.penux.uk`

### 2. Setup SSL Certificate
```bash
# Get Let's Encrypt certificate
sudo certbot certonly --standalone -d api.penux.uk -d penux.uk

# Verify certificate
sudo ls /etc/letsencrypt/live/api.penux.uk/
```

### 3. Update Configuration
- Edit `.env` with `DOMAIN=api.penux.uk`
- Update `docker-compose.yml` with domain
- Update proxy configuration (Nginx/Apache)

### 4. Deploy System
```bash
# Stop running containers (if any)
docker-compose down

# Pull latest code
git pull origin claude/distributed-sharepoint-system-kim830

# Start with new configuration
docker-compose up -d

# Verify
curl https://api.penux.uk/health
```

### 5. Verify Configuration
```bash
# Check DNS resolution
nslookup api.penux.uk

# Verify SSL certificate
curl -vI https://api.penux.uk/health

# Check API response
curl https://api.penux.uk/api/v1/status

# Check PACS
telnet api.penux.uk 11112

# Check FHIR
curl https://api.penux.uk/api/v1/fhir/
```

---

## 📊 Access Points After Configuration

| Service | URL |
|---------|-----|
| **API Server** | https://api.penux.uk |
| **API v1** | https://api.penux.uk/api/v1 |
| **Health Check** | https://api.penux.uk/health |
| **FHIR API** | https://api.penux.uk/api/v1/fhir |
| **PACS DICOM** | api.penux.uk:11112 |
| **Security Status** | https://api.penux.uk/security/status |

---

## 🔒 Security Considerations

### TLS/SSL Best Practices
- ✅ Use TLS 1.2+ only
- ✅ Strong ciphers (HIGH:!aNULL)
- ✅ HSTS headers enabled
- ✅ Certificate renewal automated

### Firewall Rules
```bash
# Allow HTTPS
sudo ufw allow 443/tcp

# Allow HTTP (for redirect)
sudo ufw allow 80/tcp

# Allow PACS DICOM
sudo ufw allow 11112/tcp

# Allow SSH (if using)
sudo ufw allow 22/tcp

# Deny everything else
sudo ufw default deny incoming
```

### Rate Limiting (Already Configured)
- API: 100 requests per 15 minutes
- DDoS protection: Automatic IP blocking
- Session timeout: 30 minutes

---

## 🧪 Testing DNS Configuration

### Test DNS Resolution
```bash
# Test A record
nslookup api.penux.uk

# Test MX (mail) if configured
nslookup -type=MX penux.uk

# Test SRV records
nslookup -type=SRV _pacs._tcp.penux.uk

# Use dig for more detail
dig api.penux.uk

# Check propagation
dig api.penux.uk +short
```

### Test API Access
```bash
# Basic connectivity
curl https://api.penux.uk/health

# With verbose output
curl -v https://api.penux.uk/health

# Check headers
curl -I https://api.penux.uk/health

# JSON response
curl https://api.penux.uk/api/v1/status | jq .
```

### Test SSL Certificate
```bash
# Check certificate details
openssl s_client -connect api.penux.uk:443

# Check certificate expiration
echo | openssl s_client -servername api.penux.uk -connect api.penux.uk:443 2>/dev/null | \
  openssl x509 -noout -dates
```

---

## 🐛 Troubleshooting

### DNS Not Resolving
```bash
# Check DNS configuration
dig api.penux.uk @8.8.8.8

# Flush local DNS cache (Linux)
sudo systemd-resolve --flush-caches

# Check from different DNS server
nslookup api.penux.uk 1.1.1.1
```

### SSL Certificate Issues
```bash
# Check certificate validity
curl -v https://api.penux.uk/ 2>&1 | grep -i certificate

# Verify certificate matches domain
openssl x509 -in penux.uk.crt -noout -text | grep DNS

# Test with openssl
openssl s_client -connect api.penux.uk:443 -servername api.penux.uk
```

### Connection Issues
```bash
# Check if port is open
telnet api.penux.uk 443

# Check firewall
sudo ufw status

# Check running services
docker-compose ps

# Check logs
docker-compose logs dss-api
```

---

## 📝 Monitoring & Maintenance

### Monitor Certificate Expiration
```bash
# Check expiry date
echo | openssl s_client -servername api.penux.uk -connect api.penux.uk:443 2>/dev/null | \
  openssl x509 -noout -dates

# Set alert for renewal (in crontab)
0 0 1 * * certbot renew
```

### Monitor DNS Resolution
```bash
# Monitor DNS changes
watch -n 60 'nslookup api.penux.uk'

# Check DNS propagation globally
# Use online tool: https://mxtoolbox.com/
```

### Backup Configuration
```bash
# Backup DNS records
# Backup SSL certificates
sudo tar -czf penux-uk-backup.tar.gz \
  /etc/ssl/certs/penux.uk.* \
  /etc/ssl/private/penux.uk.*

# Backup Docker configuration
cp docker-compose.yml docker-compose.yml.backup
cp .env .env.backup
```

---

## ✅ Checklist

- [ ] Domain registered (penux.uk)
- [ ] DNS A record added
- [ ] DNS propagation verified (nslookup)
- [ ] SSL certificate obtained (Let's Encrypt or purchased)
- [ ] Certificate copied to /etc/ssl/
- [ ] Nginx/Apache configured
- [ ] Firewall rules updated
- [ ] .env file updated with domain
- [ ] Docker-compose restarted
- [ ] API responds at https://api.penux.uk
- [ ] SSL certificate valid (curl -v)
- [ ] FHIR API accessible
- [ ] PACS DICOM connection working
- [ ] Security headers present

---

## 🔗 References

- **Let's Encrypt:** https://letsencrypt.org/
- **Certbot Documentation:** https://certbot.eff.org/docs/
- **Nginx SSL Config:** https://nginx.org/en/docs/http/ngx_http_ssl_module.html
- **Apache SSL Config:** https://httpd.apache.org/docs/2.4/mod/mod_ssl.html
- **DNS Records:** https://mxtoolbox.com/

---

**Domain:** penux.uk  
**Subdomain:** api.penux.uk  
**Status:** Ready for configuration  
**Updated:** July 30, 2024
