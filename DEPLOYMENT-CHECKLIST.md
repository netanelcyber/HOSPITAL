# Kunena 7.0.7 on Joomla 6 - Quick Deployment Checklist

## 🔒 Security Pre-Flight

### System Requirements ✅
- [ ] Joomla version: 6.0.4 or later (currently: ____)
- [ ] PHP version: 8.2.0 or later (currently: ____)
- [ ] MySQL 8.0.16+ OR MariaDB 10.4+ (currently: ____)
- [ ] PHP Extensions: dom, gd, json, pcre, SimpleXML, fileinfo, mbstring installed

### Security Audit
- [ ] Run Joomla Security Check (Admin → System Information)
- [ ] Review installed extensions for vulnerabilities
- [ ] Disable or remove: SP Page Builder, Page Builder CK, iCagenda (if older), Balbooa Forms
- [ ] Update all remaining extensions to latest versions
- [ ] Review file/folder permissions (755 for folders, 644 for files)

### Backup & Disaster Recovery
- [ ] Full filesystem backup created: `joomla.backup.tar.gz`
- [ ] Database backup created: `joomla_db_$(date +%Y%m%d).sql`
- [ ] Test restore backup on test system
- [ ] Document rollback procedure

## 📥 Installation Steps

### Step 1: Pre-Install
```bash
[ ] Backup complete
[ ] Extensions updated
[ ] No critical CVEs present
[ ] Server checklist completed
```

### Step 2: Download Package
```bash
[ ] Downloaded: pkg_kunena_v7.0.7_2026-07-08.zip
[ ] Verified file size: ~3.7M
[ ] Checked file integrity (if checksum provided)
```

### Step 3: Installation via Joomla
```bash
[ ] Navigate to: Admin → Extensions → Install Extensions
[ ] Upload: pkg_kunena_v7.0.7_2026-07-08.zip
[ ] Watch for error messages (note any warnings)
[ ] Wait for completion message
```

### Step 4: Post-Install Verification
```bash
[ ] Admin → Components → Kunena → Dashboard shows v7.0.7
[ ] No error messages or warnings displayed
[ ] Check database for Kunena tables:
    [ ] kunena_users
    [ ] kunena_messages
    [ ] kunena_categories
    [ ] kunena_version (shows: 7.0.7)
```

## 🔧 Security Hardening

### File System Permissions
```bash
[ ] /components/com_kunena/ → 755 (drwxr-xr-x)
[ ] /tmp/custom.scss exists and is readable only by owner
[ ] /images/ → 755 with .htaccess blocking PHP execution
[ ] /media/ → 755 with .htaccess blocking PHP execution
```

### Upload Directory Protection
```bash
[ ] .htaccess added to /images/
[ ] .htaccess added to /media/
[ ] Test: PHP files not executable in these directories
```

### Database Security
```bash
[ ] Database user has limited permissions (not root)
[ ] Database backups encrypted
[ ] Database accessible only from localhost
```

## ✅ Functional Testing

### Forum Functionality
- [ ] Can access forum frontend
- [ ] Can access admin forum dashboard
- [ ] Can create new category
- [ ] Can create new post/topic
- [ ] Can edit own posts
- [ ] Can view forum statistics
- [ ] User profile integration works
- [ ] PM functionality works (if enabled)

### Admin Functions
- [ ] Forum settings accessible and editable
- [ ] Category management works
- [ ] User management works
- [ ] Moderation panel functional
- [ ] Plugin system working
- [ ] Media manager shows forum media

### Integration
- [ ] Joomla users can login to forum
- [ ] User profile sync working
- [ ] Menu items for forum display correctly
- [ ] Search integration functional (if enabled)

## 🛡️ Security Testing

### File Upload Security
```bash
[ ] Test: Upload text file → should work
[ ] Test: Upload PHP file → should be blocked or show as text
[ ] Test: Upload file with double extension (e.g., .php.txt) → blocked
[ ] Test: Access uploaded file in browser → correct behavior observed
```

### SQL Injection Test (Admin Only)
```bash
[ ] In forum search, try: ' OR 1=1 --
[ ] Result: Should return no results or error, NOT all posts
```

### XSS Prevention Test
```bash
[ ] Create post with: <script>alert('XSS')</script>
[ ] Result: Script tags should be escaped/removed, not executed
```

## 📊 Performance Baseline

- [ ] Page load time recorded: ____ ms
- [ ] Database query performance: ____ ms
- [ ] Memory usage baseline: ____ MB
- [ ] No PHP errors in logs (check /logs/)

## 📝 Documentation

- [ ] Installation date recorded: ____
- [ ] Admin credentials secured: ____ (use password manager)
- [ ] Custom configuration documented: ____
- [ ] Runbook created for operations team
- [ ] Disaster recovery plan reviewed

## 🔐 Post-Deployment Security

### Ongoing Monitoring
- [ ] Setup log monitoring for:
  - [ ] Failed login attempts
  - [ ] File upload attempts
  - [ ] Database errors
  - [ ] PHP errors

### Regular Maintenance
- [ ] Weekly: Review admin logs
- [ ] Weekly: Check for extension updates
- [ ] Monthly: Review security advisories
- [ ] Monthly: Test backup restoration
- [ ] Quarterly: Full security audit
- [ ] Quarterly: Update security configurations

### Update Monitoring
- [ ] Subscribed to Kunena security updates
- [ ] Subscribed to Joomla security advisories
- [ ] Subscribed to CVE feeds for installed extensions
- [ ] Process defined for emergency security patches

## 🚨 Emergency Contacts

- Kunena Support: security@kunena.org
- Joomla Security: https://developer.joomla.org/security-centre.html
- Hosting Provider Support: __________________
- Organization Security Team: __________________

## 📋 Sign-Off

- [ ] Installation completed successfully
- [ ] All tests passed
- [ ] Security checklist complete
- [ ] No critical issues remain

**Installed By:** ________________  
**Date:** ________________  
**Reviewed By:** ________________  
**Approved By:** ________________  

---

**For Support:** See SECURITY-ADVISORY-JOOMLA6-KUNENA.md  
**For Issues:** See CVE-ANALYSIS-KUNENA-7.0.7.md
