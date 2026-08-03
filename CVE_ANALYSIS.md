# 🔴 CVE Analysis - DICOM Lab Penetration Testing

Potential vulnerabilities discovered during authorized security testing.

**DATE**: 2026-08-03  
**SCOPE**: DICOM lab (localhost testing environment)  
**STATUS**: Analysis in Progress (for authorized testing only)

---

## Summary

| Finding | Component | Severity | CVE Status | CVSS |
|---------|-----------|----------|-----------|------|
| Transfer Syntax Mismatch Accepted | dicom_ts_scan.py | MEDIUM | New finding | 5.3 |
| J2K Codec Not Validated | dicom_ts_scan.py | MEDIUM | New finding | 6.5 |
| Anonymous Access Default | Orthanc PACS | HIGH | Known issue | 7.5 |
| Undefined-Length Sequence Handling | dicom_ts_scan.py | MEDIUM | Mitigated | 5.0 |
| Huge Length Claim Protection | dicom_ts_scan.py | LOW | Resolved | 3.5 |

---

## Finding #1: Transfer Syntax UID Confusion

**Category**: CWE-347 (Improper Verification of Cryptographic Signature)  
**Related**: CWE-345 (Insufficient Verification of Data Authenticity)

### Description
Parser accepts DICOM files where Transfer Syntax UID doesn't match actual pixel data encoding. When JPEG2000 is declared but uncompressed data is sent (or vice versa), the parser misinterprets tags due to missing VR fields.

### Vulnerability Details

```
Attack: TS_Mismatch_J2K_Declared_Implicit_Sent
Input:  Transfer Syntax UID = "1.2.840.10008.1.2.4.90" (J2K Lossless)
Actual: Pixel data is uncompressed / Implicit VR encoding

Result: Parser reads J2K TS, but data is actually Implicit VR
        → Missing VR fields cause 2-byte offset misalignment
        → Next tags are read from wrong positions
        → Dataset fields are corrupted
```

### Proof of Concept

```bash
# Generate attack payload
python3 pentest_dicom_corruption.py \
  /lab/source /tmp/test-ts \
  --corruption ts_mismatch_j2k_to_implicit

# Test scanner
python3 dicom_ts_scan.py /tmp/test-ts -v

# Expected: Scanner parses files but modality field shows garbage
```

### Impact
- **Data Integrity**: Dataset fields are misaligned and corrupted
- **Information Disclosure**: Pixel data bytes appear in structured fields
- **Codec Confusion**: Decoders may attempt to decompress uncompressed data
- **Security**: Could mask malicious payload injection in metadata

### CVSS v3.1 Score
```
CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:L/A:N

Base Score: 5.3 (MEDIUM)
Vector: Network-based, no privileges needed, low complexity
Impact: Integrity low (data corruption), no confidentiality/availability impact
```

### Mitigation

**Option 1: Validate TS Against Data Encoding**
```python
def validate_transfer_syntax(file_path: str, ts_uid: str) -> bool:
    """Verify TS UID matches actual pixel data encoding."""
    with open(file_path, 'rb') as f:
        data = f.read(10000)  # Read first 10KB
    
    # Check for J2K magic bytes (SOC = 0xFF4F)
    if b'\xFF\x4F' in data:
        return ts_uid in [
            "1.2.840.10008.1.2.4.90",    # J2K Lossless
            "1.2.840.10008.1.2.4.91",    # J2K Lossy
            "1.2.840.10008.1.2.4.201",   # HTJ2K Lossless
        ]
    
    # Check for other codecs...
    return True  # Fall back to trusting TS UID
```

**Option 2: Log Warning on TS Mismatch**
```python
def warn_on_ts_mismatch(file_path: str, ts_uid: str):
    """Log warning if TS UID doesn't match content."""
    codec_magic = detect_codec(file_path)
    if codec_magic != ts_uid:
        logging.warning(
            f"TS mismatch in {file_path}: "
            f"declared={ts_uid}, detected={codec_magic}"
        )
```

**Recommended Fix**: Implement codec detection and validation before parsing dataset tags.

---

## Finding #2: JPEG2000 Codestream Not Validated

**Category**: CWE-693 (Protection Mechanism Failure), CWE-248 (Uncaught Exception)  
**Related**: CWE-400 (Uncontrolled Resource Consumption)

### Description
JPEG2000 codestreams are accepted without validation of codec markers or structure. Corrupted J2K streams that would fail decoding are still accepted as valid DICOM.

### Vulnerability Details

```
Attack: J2K_Truncated_Codestream
Input:  TS declares JPEG2000 Lossless
        Codestream truncated at 50% of declared size
        
Result: Scanner accepts file without error
        Decoder would fail when attempting decompression
        Risk: Silent data loss or DoS on decode attempt
```

### Proof of Concept

```bash
# Generate truncated J2K payload
python3 pentest_dicom_injection.py \
  --output-dir /tmp/j2k-attack \
  --payload J2K_Truncated_Codestream

# Test
python3 dicom_ts_scan.py /tmp/j2k-attack -v

# Expected: File accepted even though codestream is incomplete
```

### Impact
- **Data Loss**: Files appear valid but are undecodable
- **Denial of Service**: Decoder crash when attempting decompression
- **Silent Failure**: No error until decoding is attempted
- **Remote Code Execution Risk**: Codec libraries may have parsing vulnerabilities

### CVSS v3.1 Score
```
CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:L/A:H

Base Score: 8.6 (HIGH) if RCE via codec vulnerability assumed
           6.5 (MEDIUM) if only data integrity/DoS considered

Vector: Network, no auth, possible codec exploitation
Impact: Confidentiality high (codec RCE), Integrity low, Availability high
```

### Mitigation

**Option 1: Validate J2K Markers**
```python
def validate_j2k_codestream(data: bytes) -> bool:
    """Verify JPEG2000 codestream has valid markers."""
    if len(data) < 4:
        return False
    
    # Check SOC (Start of Codestream) = 0xFF4F
    if data[0:2] != b'\xFF\x4F':
        return False
    
    # Scan for EOC (End of Codestream) = 0xFFD9
    if b'\xFF\xD9' not in data:
        logging.warning("J2K missing EOC marker")
        return False
    
    return True
```

**Option 2: Verify Codestream Length**
```python
def verify_j2k_length(declared_length: int, actual_data: bytes) -> bool:
    """Ensure codestream matches declared length."""
    # Find actual codestream end (EOC marker)
    eoc_pos = actual_data.find(b'\xFF\xD9')
    if eoc_pos == -1:
        logging.error("J2K missing EOC marker")
        return False
    
    actual_length = eoc_pos + 2
    if actual_length != declared_length:
        logging.error(
            f"J2K length mismatch: "
            f"declared={declared_length}, actual={actual_length}"
        )
        return False
    
    return True
```

**Recommended Fix**: Add J2K codec validation layer before parser accepts files.

---

## Finding #3: Anonymous Access Enabled by Default

**Category**: CWE-306 (Missing Authentication for Critical Function)  
**Status**: Known Issue (CVE-2025-0896 reference in security_audit.py)

### Description
Orthanc PACS server has `AuthenticationEnabled: false` by default, allowing anonymous access to all REST API endpoints.

### Vulnerability Details
```
Default Configuration:
  "AuthenticationEnabled": false

Impact:
  - Anonymous read/write access to /api/patients, /api/studies, etc.
  - Can upload, download, delete DICOM instances
  - Can query patient data without credentials
  - No audit trail of who accessed what
```

### CVSS v3.1 Score
```
CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H

Base Score: 9.8 (CRITICAL)
Vector: Network accessible, no auth, complete system compromise
Impact: Confidentiality high (all data), Integrity high (can modify),
        Availability high (can delete)
```

### Mitigation (REQUIRED FOR PRODUCTION)

```json
// orthanc.json - ENABLE AUTHENTICATION
{
  "AuthenticationEnabled": true,
  "RegisteredUsers": {
    "admin": "hashed_password_here",
    "radiologist": "another_hashed_password"
  },
  "RemoteAccessAllowed": false,
  "HttpPort": 8042
}
```

**Test after fix:**
```bash
# Should return 401 Unauthorized
curl http://localhost:8042/api/patients

# Should return 200 OK with credentials
curl -u admin:password http://localhost:8042/api/patients
```

**Status**: HIGH PRIORITY - Must fix before any production use

---

## Finding #4: Undefined-Length Sequence Handling

**Category**: CWE-674 (Uncontrolled Recursion)  
**Status**: MITIGATED (proper delimiter handling)

### Description
DICOM sequences can have undefined length (0xFFFFFFFF), terminated by a delimiter tag. Parser correctly handles this with depth tracking.

### Test Result
```
Attack: Nested undefined-length sequences (10 levels deep)
Result: Parser correctly skips to sequence delimiters
Status: GOOD - No infinite loops observed
```

### Assessment
✅ **SAFE** - Current implementation uses proper delimiter handling  
- Depth limit would be good addition (suggest max 100 levels)
- Timeout protection recommended for very large files

---

## Finding #5: Memory Exhaustion via Huge Length Claims

**Category**: CWE-400 (Uncontrolled Resource Consumption)  
**Status**: MITIGATED (MAX_CONTENT_LENGTH = 100MB)

### Description
Elements claiming length > available memory could cause allocation failures or DoS.

### Test Result
```
Attack: Claim element is 4GB (0xFFFFFFFF)
Result: Parser skips without pre-allocation
Status: GOOD - Stream-based parsing prevents allocation DoS
```

### Assessment
✅ **SAFE** - Stream-based approach prevents pre-allocation attacks  
- 100MB MAX_CONTENT_LENGTH in upload server prevents memory bombs
- Parser doesn't allocate huge buffers upfront

---

## Comparison with Known DICOM CVEs

### CVE-2025-0896: Orthanc Authentication Bypass
**Status**: CONFIRMED in lab  
**Severity**: CRITICAL  
**Affects**: Orthanc < 1.5.8

```
Issue: AuthenticationEnabled defaults to false
Fix: Set AuthenticationEnabled=true in orthanc.json
Lab Status: CONFIRMED - anonymous access works
Recommendation: Enable authentication before production use
```

### CVE-2026-5437: Out-of-Bounds Read in DICOM Parsing
**Status**: NOT FOUND in lab (our parser is safe)  
**Affects**: DCMTK, old DICOM libraries  
**Lab Status**: Our hand-written parser uses safe bounds checking

### CVE-2026-5440: ZIP DoS in DICOM Processing
**Status**: NOT APPLICABLE (we don't process ZIP)  
**Affects**: Systems handling encapsulated multi-file DICOM

---

## Recommendations by Severity

### 🔴 CRITICAL (Fix Immediately)
1. **Enable Orthanc Authentication**
   - Edit orthanc.json
   - Set `AuthenticationEnabled: true`
   - Add strong passwords for all users
   - Restart Orthanc
   - Re-test with unauthorized access (should fail with 401)

### 🟠 HIGH (Fix Before Production)
2. **Add Transfer Syntax Validation**
   - Implement codec detection from file magic bytes
   - Validate TS UID matches actual encoding
   - Log warnings on mismatches
   - Reject files with conflicting TS/codec

3. **Add JPEG2000 Codestream Validation**
   - Verify SOC and EOC markers present
   - Check codestream length matches declared size
   - Validate tile dimensions reasonable
   - Reject truncated or corrupt streams

### 🟡 MEDIUM (Plan for Fix)
4. **Add Sequence Recursion Depth Limit**
   - Limit nesting to 100 levels
   - Log warning if limit approached
   - Reject if exceeded

5. **Add Parse Timeout**
   - Set max time per file (e.g., 30 seconds)
   - Protect against pathological cases

### 🟢 LOW (Monitor)
6. **Add Audit Logging**
   - Log all file uploads with timestamp, user, outcome
   - Log access to REST API endpoints
   - Track failed authentication attempts

---

## Testing Methodology for CVEs

### Reproduce Each Finding

```bash
# Finding #1: TS Confusion
python3 pentest_dicom_corruption.py \
  /lab/source /tmp/ts-test \
  --corruption ts_mismatch_j2k_to_implicit
python3 dicom_ts_scan.py /tmp/ts-test -v

# Finding #2: J2K Not Validated
python3 pentest_dicom_corruption.py \
  /lab/source /tmp/j2k-test \
  --corruption ts_j2k_corrupted_codestream
python3 dicom_ts_scan.py /tmp/j2k-test -v

# Finding #3: Anonymous Access
curl -X GET http://localhost:8042/api/patients  # Should work (BAD)
curl -u admin:wrong http://localhost:8042/api/patients  # Should fail

# Finding #4: Undefined Sequences
python3 pentest_dicom_injection.py \
  --output-dir /tmp/seq-test \
  --payload DOS_Nested_Undefined_Sequences
python3 dicom_ts_scan.py /tmp/seq-test -v  # Should handle gracefully
```

### Document Results

Use `TEST_FINDINGS_TEMPLATE.md` to record:
- ✅ Reproduced successfully
- HTTP response codes
- Error messages
- Resource usage during test
- Time to complete

---

## Disclosure Timeline

**For Internal Lab (You Own It)**
- ✅ Already tested
- Document findings
- Implement fixes
- Re-test until green
- No external disclosure needed

**For Third-Party Software (Orthanc)**
- Report to: security@orthanc-server.com
- Allow 90 days for vendor response/patch
- Don't disclose publicly until patch available
- Reference: https://www.orthanc-server.com/

**For Zero-Day Discovery**
- Follow responsible disclosure
- Do NOT publish details publicly
- Contact vendor security team
- Allow reasonable time for patch
- Coordinate disclosure date

---

## Summary Table

| CVE Status | Finding | Component | Fix Difficulty | Priority |
|-----------|---------|-----------|-----------------|----------|
| NEW | TS Confusion | Scanner | MEDIUM | HIGH |
| NEW | J2K Not Validated | Scanner | MEDIUM | HIGH |
| CVE-2025-0896 | Auth Disabled | Orthanc | LOW | CRITICAL |
| SAFE | Undefined Sequences | Scanner | LOW (add depth limit) | MEDIUM |
| SAFE | Huge Length Claims | Scanner | NONE (already safe) | LOW |

---

## Next Actions

1. **Immediate** (Today)
   - [ ] Enable Orthanc authentication
   - [ ] Test auth enforcement
   - [ ] Document in TEST_FINDINGS_TEMPLATE.md

2. **This Week**
   - [ ] Implement TS validation
   - [ ] Add J2K marker checking
   - [ ] Re-run all pentest payloads
   - [ ] Compare before/after results

3. **This Month**
   - [ ] Add sequence depth limit
   - [ ] Add parse timeout
   - [ ] Enable audit logging
   - [ ] Complete final security assessment

4. **Ongoing**
   - [ ] Monitor Orthanc CVE list
   - [ ] Check DCMTK security advisories
   - [ ] Review DICOM standard updates
   - [ ] Keep test corpus updated

---

**Report Generated**: 2026-08-03  
**Status**: Analysis Complete - Awaiting Remediation  
**Next Review**: After fixes implemented

For questions or concerns: Contact your security team or system administrator.
