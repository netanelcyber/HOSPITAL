# 🔒 Security Testing Guide for DICOM Lab

This guide covers **authorized security testing** on systems you own or operate. All testing must be conducted within legal and ethical boundaries.

## Quick Start: Security Audit

Run the built-in security audit on your lab setup:

```bash
python3 security_audit.py --orthanc-url http://127.0.0.1:8042 --orthanc-json ./orthanc.json
```

Output includes:
- Orthanc PACS configuration assessment (authentication, remote access, storage limits)
- Python code security checks (input validation, SQL injection, file permissions)
- Network exposure analysis (Docker binding, port access)
- DICOM parsing safety validation (buffer bounds, exception handling, DoS protection)
- Known CVE references for your Orthanc version
- Overall security score (0-100%)

### Interpreting Results

- **✓ GREEN (Pass)** — Security check passed, no action needed
- **✗ RED (Fail)** — Critical security issue, must fix before production
- **⚠ YELLOW (Warn)** — Security concern, review for your use case

Example output:
```
Orthanc PACS Security Audit
============================================================

[1] Service Health
  ✓ Orthanc responding (v1.5.7)

[2] Authentication
  ✗ Authentication may be disabled (anonymous access)

...

OVERALL SCORE: 62%
```

---

## Legal Penetration Testing Framework

**IMPORTANT:** Only test systems you own, operate, or have explicit written authorization to test.

### Before You Start: Rules of Engagement

Create a test plan document (`TEST_PLAN.md`) covering:

```markdown
# Test Plan - DICOM Lab Penetration Testing

## Scope
- Systems: [e.g., localhost Orthanc, local Flask dashboard]
- Applications: security_audit.py, dicom_ts_scan.py, lab_dashboard.py, dicom_upload_server.py
- Testing Window: [dates/times]

## Authorization
- Owner/Operator: [your name]
- Date Authorized: [date]
- Out of Scope: [any systems NOT being tested]

## Rules of Engagement
- Testing conducted on isolated network only
- No data exfiltration
- No DoS/resource exhaustion attacks beyond controlled testing
- Findings documented and resolved internally
- No third-party disclosure without legal review
```

### Security Testing Categories

#### 1. Input Validation Testing

Test fuzzy/malformed DICOM files against `dicom_ts_scan.py`:

```bash
# Create malformed DICOM samples
python3 -c "
import os
os.makedirs('/tmp/malformed', exist_ok=True)

# File 1: Truncated file meta
with open('/tmp/malformed/truncated.dcm', 'wb') as f:
    f.write(b'DICM' + b'\\x00' * 136)  # Too short

# File 2: Invalid transfer syntax UID
with open('/tmp/malformed/bad_uid.dcm', 'wb') as f:
    f.write(b'\\x00' * 128 + b'DICM')
    f.write(b'\\x02\\x00\\x10\\x00\\x55\\x49\\x0a\\x00')  # TS tag
    f.write(b'9.9.9.9.9.9.9.9\\x00')  # Invalid UID

# File 3: Circular references (if using sequences)
# File 4: Extremely large value lengths
"

# Test scanner against malformed files
python3 dicom_ts_scan.py /tmp/malformed -v
```

Expected behavior: Scanner should handle errors gracefully without crashing or revealing internal details.

#### 2. Network Security Testing

Test network exposure:

```bash
# Check if ports are publicly accessible (from different machine on network)
nmap -p 8042,4242,8765,5000 localhost

# Test Orthanc without authentication (if enabled as intended)
curl -X GET http://localhost:8042/api/patients

# Test DICOM DIMSE protocol on port 4242
# Use dcmtk tools: dcmqr, dcmsend, etc.
dcmqr -aec ORTHANC localhost 4242
```

#### 3. DICOM Upload Server Testing

Test `dicom_upload_server.py` input handling:

```bash
# Start server
python3 dicom_upload_server.py --port 8765 &

# Test 1: Upload non-DICOM file
curl -F "file=@/etc/passwd" http://localhost:8765/upload

# Test 2: Upload extremely large file (>100MB)
dd if=/dev/zero of=/tmp/large.bin bs=1M count=150
curl -F "file=@/tmp/large.bin" http://localhost:8765/upload

# Test 3: Path traversal attempt
# (Should be blocked by tempfile.TemporaryDirectory)

# Test 4: Special characters in filename
touch "/tmp/test;rm -rf /.dcm"
curl -F "file=@/tmp/test;rm -rf /.dcm" http://localhost:8765/upload
```

Expected: Server rejects non-DICOM, enforces size limits, handles special chars safely.

#### 4. Orthanc Authentication Testing

Test authentication mechanisms:

```bash
# If AuthenticationEnabled is true:
# Test 1: Valid credentials
curl -u admin:orthanc http://localhost:8042/api/patients

# Test 2: Invalid credentials
curl -u admin:wrong http://localhost:8042/api/patients  # Should be 401

# Test 3: Missing credentials
curl http://localhost:8042/api/patients  # Should be 401

# Test 4: Check session handling
curl -X POST -u admin:orthanc http://localhost:8042/api/auth/user
```

#### 5. DICOM File Parsing Safety

Test for buffer overflow and parsing issues:

```bash
# Use DICOM fuzzing tools
# Option 1: AFL (American Fuzzy Lop) — if available
afl-fuzz -i corpus -o findings -- python3 dicom_ts_scan.py @@

# Option 2: Manual edge case testing
python3 -c "
import struct
import os

os.makedirs('/tmp/edge-cases', exist_ok=True)

# Case 1: Undefined-length sequence
with open('/tmp/edge-cases/undefined_seq.dcm', 'wb') as f:
    f.write(b'\\x00' * 128 + b'DICM')
    # Add VR=SQ with undefined length (FFFFFFFF)
    f.write(b'\\x10\\x00\\x20\\x00\\x53\\x51\\x00\\x00\\xFF\\xFF\\xFF\\xFF')

# Case 2: Explicit VR big-endian
with open('/tmp/edge-cases/explicit_be.dcm', 'wb') as f:
    f.write(b'\\x00' * 128 + b'DICM')
    f.write(b'\\x02\\x00\\x10\\x00\\x55\\x49\\x00\\x12')  # TS UID tag
    f.write(b'1.2.840.10008.1.2.2\\x00')  # Explicit VR Big-Endian

# Case 3: Element with declared length > actual data
with open('/tmp/edge-cases/truncated_value.dcm', 'wb') as f:
    f.write(b'\\x00' * 128 + b'DICM')
    f.write(b'\\x10\\x10\\x10\\x00\\x4c\\x4f\\x00\\x10')  # Patient Name, length=16
    f.write(b'Short')  # But only 5 bytes provided
"

python3 dicom_ts_scan.py /tmp/edge-cases -v
```

#### 6. Dashboard Web Security Testing

Test `lab_dashboard.py` web interface:

```bash
# Start dashboard
python3 lab_dashboard.py --port 5000 &

# Test 1: XSS via filename
# Upload file with special characters in name
touch "/tmp/<script>alert('xss')</script>.dcm"
curl -F "file=@/tmp/<script>alert('xss')</script>.dcm" http://localhost:5000/api/upload

# Test 2: CSRF testing (check security headers)
curl -v http://localhost:5000/ 2>&1 | grep -i "security\|set-cookie"

# Test 3: Session/cookie security
curl -v -c cookies.txt -b cookies.txt http://localhost:5000/

# Test 4: Path traversal in reports
curl http://localhost:5000/scan?csv=../../../etc/passwd

# Test 5: SQL Injection (if applicable)
curl "http://localhost:5000/?patient=%27%20OR%20%271%27=%271"
```

---

## Vulnerability Reporting

If you discover a genuine security issue in your testing:

1. **Document thoroughly**: reproduction steps, impact, affected component
2. **Assess severity**: Critical/High/Medium/Low
3. **Do not disclose publicly** until patched
4. **Internal resolution only** (you own the system)

For open-source vulnerabilities (Orthanc, DCMTK):
- Report via official security advisories
- Reference: https://www.orthanc-server.com/
- Allow 90-day disclosure window for patching

---

## Common Findings & Mitigations

### Finding: Anonymous Orthanc Access
**Severity**: High
```bash
# Mitigation: Enable authentication in orthanc.json
"AuthenticationEnabled": true,
"RegisteredUsers": {
  "admin": "your_secure_password_hash"
}
# Restart Orthanc
docker-compose restart orthanc
```

### Finding: World-Readable File Permissions
**Severity**: Medium
```bash
# Mitigation: Restrict file permissions
chmod 600 orthanc.json
chmod 600 dicom_*.py lab_dashboard.py
find /lab -type f -exec chmod 600 {} \;
```

### Finding: DICOM PixelData Decoding
**Severity**: Medium (RCE via codec)
```bash
# Already mitigated in dicom_ts_scan.py — never reads PixelData
# Verify: grep -n "PixelData" dicom_ts_scan.py
# Should NOT be decompressed
```

### Finding: Missing Input Validation
**Severity**: Medium
```bash
# Mitigation: Use os.path.basename() and validate file types
# Check: dicom_upload_server.py line 204 uses tempfile.TemporaryDirectory()
# which prevents path traversal
```

---

## Testing Checklist

- [ ] Run `python3 security_audit.py` and review results
- [ ] Test malformed DICOM file handling
- [ ] Test network port accessibility
- [ ] Test upload server with edge-case files
- [ ] Test Orthanc authentication (if enabled)
- [ ] Test dashboard for XSS/CSRF
- [ ] Review file permissions on sensitive files
- [ ] Check for debug/verbose output in production config
- [ ] Verify DICOM PixelData is never decompressed
- [ ] Document all findings in TEST_FINDINGS.md
- [ ] Remediate critical/high findings
- [ ] Re-test after fixes

---

## Resources

- **OWASP Top 10**: https://owasp.org/www-project-top-ten/
- **DICOM Security**: https://www.dicomstandard.org/ (PS3.2)
- **Orthanc Security**: https://www.orthanc-server.com/
- **DCMTK**: https://dicom.offis.de/dcmtk.php
- **CVE Database**: https://nvd.nist.gov/

---

## Next Steps

1. Run security audit: `python3 security_audit.py`
2. Create `TEST_PLAN.md` with your scope and authorization
3. Execute targeted tests from this guide
4. Document findings in `TEST_FINDINGS.md`
5. Remediate critical issues
6. Re-test until security score reaches acceptable threshold

**Remember**: This testing is for your lab only. Always obtain written authorization before testing any system you don't own.
