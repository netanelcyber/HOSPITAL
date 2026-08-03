# 📤 CVE Findings Distribution & Reporting

Where to send your penetration testing findings and vulnerability reports.

---

## Quick Reference: Who to Contact

### 🔴 CRITICAL: Orthanc Authentication Bypass (CVE-2025-0896)

**Your Situation**: Testing your own lab setup
- ✅ **Keep findings internal** — No external reporting needed
- ✅ Fix in your orthanc.json (enable AuthenticationEnabled)
- ✅ Document remediation in TEST_FINDINGS_TEMPLATE.md

**If Orthanc is third-party**: Report via official channels
- **Contact**: security@orthanc-server.com
- **Website**: https://www.orthanc-server.com/
- **Allow**: 90 days for vendor to patch before public disclosure
- **Reference**: CVE-2025-0896 (already known/published)

---

### 🟠 HIGH: Transfer Syntax Mismatch & J2K Validation (NEW Findings)

**Your Situation**: Discovered in your own lab code
- ✅ **Your responsibility** — Fix in your dicom_ts_scan.py
- ✅ Document findings in TEST_FINDINGS_TEMPLATE.md
- ✅ Implement mitigations
- ✅ Re-test to verify fixes

**If Using DCMTK/Open Source**: Follow responsible disclosure
- **Contact**: Through project's security policy
- **Timeline**: 90 days remediation window
- **Process**: Report → Vendor patches → Coordinated disclosure
- **Never**: Publish exploit code before vendor patches

**If Used in Production**: Escalate to your security team
- Document everything
- Implement compensating controls
- Plan remediation timeline
- Get stakeholder approval

---

## Complete Distribution Matrix

| Finding | Component | Owner | Report To | Timeline | Status |
|---------|-----------|-------|-----------|----------|--------|
| CVE-2025-0896 | Orthanc | You | Keep internal | N/A (lab only) | ✓ Fix it |
| TS Mismatch | dicom_ts_scan.py | You | Internal tracking | Fix before prod | TODO |
| J2K Not Validated | dicom_ts_scan.py | You | Internal tracking | Fix before prod | TODO |
| Seq Depth Limit | dicom_ts_scan.py | You | Internal tracking | Recommended | TODO |
| (None) | Security | All | Team lead | Ongoing | — |

---

## Reporting Procedures by Audience

### 1️⃣ INTERNAL: Your Own Lab/Company

**Use**: TEST_FINDINGS_TEMPLATE.md

```markdown
File: /tmp/pentest-findings-YYYY-MM-DD.md

Contents:
  ☐ Executive summary (1 paragraph)
  ☐ Vulnerabilities found (table)
  ☐ Risk assessment (CVSS scores)
  ☐ Proof of concept (reproduction steps)
  ☐ Mitigation plan (timeline & owner)
  ☐ Test results after fixes
  ☐ Approval from stakeholders
  ☐ Remediation sign-off
```

**Distribution**:
- Send to: Security team lead / CTO / Project manager
- Format: PDF or DOCX (use `docx` skill or `pdf` skill)
- Audience: Technical + management
- Sensitivity: Confidential (internal use only)

---

### 2️⃣ ORTHANC PROJECT: Third-Party Vendor Reporting

**Vendor**: Orthanc Server (https://www.orthanc-server.com/)

**Contact Methods**:

```
Email: security@orthanc-server.com

Subject: Security Advisory: [CVE-2025-0896 | New Finding]
         DICOM Transfer Syntax Mismatch

Description: [See template below]

Timeline: 
  - Day 1: Report sent
  - Day 90: Deadline for vendor patch
  - Day 91: Public disclosure (if no patch)
```

**Email Template**:

```
Subject: Security Advisory: DICOM Transfer Syntax UID Mismatch Vulnerability

To: security@orthanc-server.com

---

VULNERABILITY REPORT

Title: Transfer Syntax UID Mismatch Accepted Without Validation

Component: dicom_ts_scan.py (DICOM parser)

Severity: CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:L/A:N
Score: 5.3 MEDIUM (8.6 HIGH if codec RCE considered)

CWE: CWE-347 (Improper Verification of Cryptographic Signature)
     CWE-345 (Insufficient Verification of Data Authenticity)

Description:
  Parser accepts DICOM files where the declared Transfer Syntax UID
  does not match the actual pixel data encoding. This causes dataset
  tag misalignment and data corruption when the VR field presence
  differs from what the TS UID indicates.

Proof of Concept:
  1. Create DICOM file declaring TS = JPEG2000 Lossless
  2. Fill pixel data with uncompressed (Implicit VR) encoding
  3. Parse with dicom_ts_scan.py
  Result: Parser misaligns tags, modality field shows garbage

Impact:
  - Data integrity violation
  - Information disclosure (pixel bytes in metadata)
  - Potential codec confusion attacks
  - Silent data corruption

Mitigation:
  - Implement codec detection from file magic bytes
  - Validate TS UID matches actual encoding
  - Reject mismatches or log warnings

Affected Versions: [Your version]
Fixed Versions: [Unknown - awaiting vendor response]

Timeline:
  - 2026-08-03: Vulnerability discovered
  - 2026-08-05: Report sent to vendor
  - 2026-11-03: Public disclosure deadline (90 days)

Testing Environment:
  - OS: Linux
  - Python: 3.10
  - DICOM Parser: dicom_ts_scan.py (hand-written)

---

Please acknowledge receipt of this report and provide an estimated
timeline for patch development.

Thank you,
[Your Name]
```

**After Vendor Responds**:

```
[ ] Day 1-5: Vendor acknowledges receipt
[ ] Day 5-30: Vendor develops patch
[ ] Day 30-60: Vendor tests patch
[ ] Day 60-90: Vendor publishes patch
[ ] Day 90+: You can disclose publicly (reference vendor patch)
```

---

### 3️⃣ PUBLIC DISCLOSURE: After Vendor Patch Available

**Only after vendor publishes a patch**, can you disclose publicly:

```markdown
# DICOM Transfer Syntax Mismatch Vulnerability (CVE-XXXX-XXXXX)

## Vulnerability Description
DICOM parsers that don't validate Transfer Syntax UID against actual
pixel data encoding can be exploited to cause dataset corruption.

## Affected Component
dicom_ts_scan.py (hand-written DICOM parser)

## Severity
CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:N/I:L/A:N = 5.3 MEDIUM

## Timeline
- 2026-08-03: Discovered in penetration testing
- 2026-08-05: Reported to developers
- 2026-10-01: Patch released (v2.1)
- 2026-11-03: Public disclosure

## Mitigation
Upgrade to dicom_ts_scan.py v2.1 or later, which validates
Transfer Syntax UID against detected codec from file magic bytes.

## References
- [CVE Details](#)
- [Vendor Patch](#)
- [Proof of Concept](#) (link to responsible disclosure page)
```

---

## When NOT to Disclose Publicly

❌ **Never disclose before vendor patches if**:
- Vendor hasn't been notified
- 90-day window hasn't elapsed
- No patch available yet
- Vendor specifically asked for extended embargo

❌ **Never publish**:
- Exploit code before patch available
- Zero-day details without coordination
- Patient data or proprietary info
- Commands to compromise live systems

✅ **OK to publish**:
- After vendor patches (with credit to vendor)
- Generic vulnerability description (without exploit)
- Mitigation steps (how to fix)
- Your own code findings (you own the code)

---

## Distribution Checklist

### For Lab-Only (Internal) Findings

```markdown
[ ] Step 1: Document in TEST_FINDINGS_TEMPLATE.md
    ├─ Vulnerability description
    ├─ Proof of concept (reproduction steps)
    ├─ Impact assessment
    └─ CVSS score

[ ] Step 2: Create remediation plan
    ├─ Fix details
    ├─ Implementation timeline
    ├─ Owner assigned
    └─ Approval from stakeholders

[ ] Step 3: Implement fixes
    ├─ Code changes committed
    ├─ Tests pass
    └─ Documentation updated

[ ] Step 4: Re-test with pentest payloads
    ├─ Run pentest_dicom_injection.py again
    ├─ Run pentest_dicom_corruption.py again
    ├─ Verify scanner rejects/warns on issues
    └─ Compare before/after results

[ ] Step 5: Final sign-off
    ├─ Security team approves
    ├─ CTO signs off on deployment
    ├─ Archive findings report
    └─ Update compliance documentation
```

### For Third-Party Vendor Reporting

```markdown
[ ] Step 1: Identify vendor
    ├─ Find official security contact
    ├─ Check for CVE coordinator info
    └─ Locate responsible disclosure policy

[ ] Step 2: Prepare report
    ├─ Write vulnerability description
    ├─ Create proof of concept
    ├─ Calculate CVSS score
    └─ Include reproduction steps

[ ] Step 3: Send report
    ├─ Email to security@vendor.com
    ├─ Include timeline expectations
    ├─ Request confirmation of receipt
    └─ Save email thread

[ ] Step 4: Wait for vendor response
    ├─ Track 90-day timeline
    ├─ Follow up if no response
    ├─ Provide assistance if requested
    └─ Review patch when available

[ ] Step 5: Coordinate disclosure
    ├─ Request embargo period if needed
    ├─ Plan public announcement date
    ├─ Prepare blog post / CVE details
    └─ Publish after vendor OK
```

---

## Email Templates

### Template 1: Internal Distribution

```
To: security-team@company.com
CC: project-lead@company.com
Subject: Penetration Test Results - DICOM Lab Security Assessment

Hi team,

Attached is the security assessment report from our recent penetration
testing of the DICOM lab environment.

Key Findings:
  🔴 1 Critical issue (Orthanc authentication)
  🟠 2 High issues (DICOM parser validation)
  🟡 1 Medium issue (sequence depth limit)

Immediate Action Required:
  ☐ Enable Orthanc authentication (10 min)
  ☐ Review parser validation gaps (2 hours)
  ☐ Plan remediation timeline (1 day)

Timeline:
  - This week: Fix critical/high severity items
  - Next week: Re-test with pentest payloads
  - Month-end: Compliance sign-off

Full report: [attachment]
Questions? Contact: [your email]

---
[Your Name]
```

### Template 2: Vendor Security Report

```
To: security@vendor.com
Subject: Security Advisory: DICOM Transfer Syntax Validation

Hi [Vendor Security Team],

I've identified a potential vulnerability in [Component] that I'd like
to report responsibly. I'm following coordinated disclosure practices
and will allow 90 days for your team to develop and test a patch before
any public disclosure.

Vulnerability Summary:
  Title: [Brief description]
  Severity: [CVSS score]
  Type: [CWE-XXX]

Impact: [What could an attacker do?]

Proof of Concept: [Reproduction steps - see attachment]

Timeline Expectations:
  - Notification: Today (2026-08-05)
  - Patch development: 30 days
  - Patch testing: 30 days
  - Public disclosure: 2026-11-05 (90 days)

I'm happy to:
  ☐ Clarify any details about the vulnerability
  ☐ Help test patches before release
  ☐ Coordinate timing of public disclosure
  ☐ Provide additional proof-of-concept code

Please confirm receipt and let me know your team's timeline.

Thank you,
[Your Name]
[Your Title]
[Your Contact Info]
```

---

## CVE Coordination Resources

### Official CVE Processes

| Organization | Process | Contact |
|--------------|---------|---------|
| MITRE | CVE Assignment | https://www.cve.org/cveprocess/overview |
| NVD | Vulnerability Database | https://nvd.nist.gov/ |
| CERT/CC | Coordination | https://www.cert.org/contact/index.html |
| FIRST | Information Sharing | https://www.first.org/ |

### Responsible Disclosure Standards

- **CWE**: https://cwe.mitre.org/
- **CVSS Calculator**: https://www.first.org/cvss/calculator/3.1
- **ISO 29147**: Vulnerability Disclosure Standard
- **Coordinated Vulnerability Disclosure**: https://cheatsheetseries.owasp.org/

---

## What NOT to Do

❌ **Don't**:
1. Post on social media before vendor patches
2. Share exploit code in forums
3. Disclose patient/proprietary data
4. Skip vendor notification
5. Demand immediate action without timeline
6. Publish CVE details without CVE ID
7. Target multiple organizations simultaneously

✅ **Do**:
1. Report to vendor first (90 days)
2. Follow their responsible disclosure policy
3. Keep information confidential until patch
4. Reference CVE ID when publicly disclosing
5. Coordinate timing with vendor
6. Credit vendor/security team in disclosure

---

## Post-Remediation Steps

After fixes are implemented and verified:

### 1. Update Documentation

```markdown
# REMEDIATION REPORT

## Summary
All critical and high-severity vulnerabilities have been addressed.

## Issues Fixed
✓ Orthanc authentication enabled
✓ Transfer Syntax validation implemented
✓ JPEG2000 marker validation added

## Testing
✓ Pentest payloads re-tested
✓ All injection attacks now rejected
✓ No false positives on legitimate files

## Approval
☐ Security team sign-off
☐ Technical lead approval
☐ Compliance review completed

Date: [2026-XX-XX]
```

### 2. Archive Findings

```bash
# Save original findings
tar czf pentest-findings-2026-08-03.tar.gz \
  CVE_ANALYSIS.md \
  TEST_FINDINGS_TEMPLATE.md \
  /tmp/dicom-pentest-results.json \
  /tmp/dicom-corrupted/

# Store securely (not in git, use secure backup)
```

### 3. Update Compliance Records

- Add to vulnerability register
- Update risk matrix
- Document remediation timeline
- Update security policies if needed
- Schedule re-audit (6-12 months)

---

## Summary

**For Your Lab**: 
- ✅ Fix internally
- ✅ Document in TEST_FINDINGS_TEMPLATE.md
- ✅ Archive findings
- No external reporting needed

**For Third-Party Code**:
- Follow responsible disclosure (90 days)
- Email vendor security team
- Wait for patch before public disclosure
- Coordinate timing for CVE announcement

**Never** disclose publicly before vendor patches.

---

**Ready to send findings? Check the checklist above, choose your template, and use it!**
