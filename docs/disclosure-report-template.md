# Vulnerability Disclosure Report — Template & Worked Example

**Purpose:** A ready-to-adapt draft for filing a private security advisory (e.g. via GitHub's "Report a vulnerability" flow on `openemr/openemr`).

> ⚠️ **Read before using**
> - This is a **draft template**, not a confirmed finding. Every field marked `<<FILL>>` must be replaced with evidence **you** observed on a system **you own or are authorized to test**.
> - **Do not submit an unverified report.** Filing speculative or AI-generated "findings" wastes maintainer time and can get you blocklisted. Verify the behavior end-to-end first.
> - **Do not include a weaponized exploit.** Reproduction steps are principle-level; provide enough for a maintainer to reproduce, not a copy-paste mass-exploitation script.
> - The worked example below models the **confirmed** `session + CSRF but no ACL` pattern. ⚠️ The *specific* `message_list.php` export case is **already CVE-2026-25124, fixed in 8.0.0** — filing that exact one is a **duplicate**. Point this template at a **different, as-yet-unreported** endpoint that exhibits the same pattern (your SUSP-BIO-08 hunt result).

---

## The report

### Title
`Broken Access Control — <<endpoint/file>> allows low-privilege users to <<action>> without ACL check`

*Example:* `Broken Access Control — patient document export endpoint allows Receptionist-level users to download PHI without ACL check`

Keep it: **vulnerability class + component + one-line impact**. Maintainers triage by title.

---

### Version
```
Product:        OpenEMR
Version tested: <<8.2.0 (released 2026-07-08 — current stable)>>   ← exact, from Administration → About
Also repro on:  <<master @ <short-sha>>>        ← proves NOT already fixed
Commit / tag:   <<e.g. v8_2_0 @ <short-sha>>>   ← if you built from source
Install type:   <<Docker image tag / distro package / source build>>
Environment:    <<PHP version, DB engine+version, OS>>
```
**Always test against the current stable (8.2.0) or `master`.** As of Aug 2026 the newest release is **8.2.0** (2026-07-08); the 2026 access-control/SQLi/XSS clusters were fixed across **8.0.0** (2026-02-11) and **8.0.0.3** (2026-03-25). If your finding only reproduces on ≤8.0.x it is likely **already fixed** — check the 8.1.0/8.2.0 release notes and closed GHSAs before filing, or it's a duplicate.

---

### Type (CWE)
```
Primary:   CWE-284  Improper Access Control
Related:   CWE-862  Missing Authorization        ← the specific sub-case for "no check at all"
           CWE-639  Authorization Bypass Through User-Controlled Key   ← if it's an IDOR variant
```
Pick the **most specific** CWE. For this pattern it's almost always **CWE-862 (Missing Authorization)** — the endpoint verifies *authentication* (session) and *CSRF*, but never checks *authorization* (ACL).

---

### Description
> *What happens and why it's a vulnerability.*

```
The endpoint <<path, e.g. interface/.../export_xyz.php>> handles a
<<GET|POST>> request that returns/modifies <<PHI or privileged data>>.

Before performing the sensitive operation, the handler validates:
  1. an authenticated session  (e.g. via the session-auth include), and
  2. a CSRF token             (CsrfUtils::verifyCsrfToken(...)).

It does NOT call any authorization check — there is no
AclMain::aclCheckCore('<<section>>', '<<subsection>>') (or equivalent
acl_check) gating the operation.

As a result, ANY authenticated user — regardless of assigned role or
ACL group — can invoke it. A low-privilege role such as "Receptionist",
which the deployment intends to restrict from <<data>>, can perform the
operation in full.

Root cause: authorization is conflated with authentication. Passing the
session + CSRF gate is treated as sufficient to proceed, so the ACL layer
is simply absent on this code path.
```

Reference the confirmed sibling to show it's a **known pattern, not a one-off** (strengthens triage):
> *"This is the same missing-authorization pattern as CVE-2026-25124 (message_list.php export), CVE-2026-25127 (Care Coordination), and CVE-2026-25131 (order types), but on a code path not covered by those fixes."*

---

### Impact
> *What an attacker gains, and the privilege level required.*

```
Privilege required:  Any authenticated OpenEMR account (lowest role suffices,
                     e.g. Receptionist). No admin, no API scope.
Attack vector:       Authenticated web request over the network (AV:N; a valid
                     low-privilege login, an over-provisioned kiosk account,
                     or a stolen low-tier credential). Note: "network-adjacent"
                     (AV:A) is a DIFFERENT CVSS value — use it only if
                     exploitation truly needs the same physical/logical LAN.
Confidentiality:     HIGH — <<n>> patients' PHI (<<names, DOB, dx, messages,
                     billing/claim data — be specific>>) exfiltrated.
Integrity:           <<HIGH if it also writes/deletes; e.g. "records can be
                     permanently deleted" — else NONE/LOW>>
Availability:        <<usually NONE for read; HIGH if it enables destructive
                     bulk delete>>

Regulatory note: exposure of PHI outside authorized scope may be a
reportable breach, but is NOT automatic — HIPAA allows a documented
low-probability-of-compromise assessment (and has exceptions), and GDPR
notification depends on risk to individuals. Direct the deployment to its
privacy/legal team for the breach assessment; do not assert reportability.

Suggested CVSS v3.1:
  <<e.g. AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:N/A:N  → 6.5 (Medium)
     bump PR:L→PR:N only if truly unauthenticated;
     add I:H/A:H if it deletes → AV:N/AC:L/PR:L/UI:N/S:U/C:H/I:H/A:H = 8.8 (High)>>
```
Be honest about `PR` (privileges required). The whole point of this class is `PR:L` — don't inflate to `PR:N` unless the endpoint is genuinely reachable pre-auth.

---

### Reproduction (principle-level — no mass-exploit script)
```
Preconditions:
  - A test OpenEMR <<version>> install YOU control.
  - Two accounts:
      A = admin (to seed data / confirm the intended restriction)
      B = a low-privilege role (e.g. Receptionist) that SHOULD be denied.

Steps:
  1. As B, log in normally and obtain a valid session cookie + the CSRF
     token OpenEMR issues to B's session.
  2. Establish the *intended* boundary from CONFIGURATION, not the UI: an
     endpoint may be intentionally callable directly even when it's absent
     from B's menus. Confirm via B's configured ACL / documented policy /
     an equivalent protected operation that B is genuinely meant to be denied
     — absence of a menu link alone does NOT prove a boundary.
  3. As B, issue the sensitive request directly to <<endpoint>>:
        <<METHOD>> <<path>>
        params: <<the minimal params, e.g. an id/range + the CSRF token>>
  4. Observe: the server returns <<the PHI / performs the action>> for B,
     despite step 2 — i.e. no authorization was enforced.
  5. (Control) Remove/blank the CSRF token → request is rejected. This proves
     the ONLY gate present is CSRF (+ session), and authorization is missing.

Evidence to attach (private advisory only):
  - Redacted request/response showing B receiving data it shouldn't.
  - The relevant source lines: the session + CsrfUtils check present, and
    the ABSENCE of any AclMain::aclCheckCore(...) before the sensitive op.
```
> Provide the **source-line evidence** — pointing at the exact file+lines where the ACL check is missing is what makes the report actionable and fast to fix. Redact real patient data; use seeded dummy records.

---

### Suggested fix
```
Add an authorization gate at the top of the handler, before any data access,
mirroring how the (now-patched) sibling endpoints were fixed:

    if (!AclMain::aclCheckCore('<<section>>', '<<subsection>>')) {
        http_response_code(403);
        exit();
    }

Choose the ACL section/subsection that matches the data's sensitivity
(e.g. 'patients'/'demo' for demographics, 'admin'/'super' for admin data,
the appropriate billing/report ACL for financial/claim data).

Defense-in-depth:
  - Add a regression test asserting a low-privilege role receives 403.
  - Audit ALL sibling endpoints that currently gate on session+CSRF only,
    to catch the rest of this class in one sweep (the pattern recurred
    across ≥4 endpoints already).
```

---

## Checklist before you hit "submit"
- [ ] Reproduced on the **latest** release (or `master`) — not an old version already fixed.
- [ ] Searched existing **GHSA advisories + CVEs** for this file/endpoint → not a duplicate.
- [ ] Removed any real PHI from evidence; used seeded dummy data.
- [ ] Reproduction is enough to verify, but **not** a turnkey exploit.
- [ ] Filed via **private** advisory (`Security → Report a vulnerability`), **not** a public issue.
- [ ] Proposed a concrete fix + CVSS vector.
- [ ] You have **written authorization** for the system you tested.

---

*This template is a defensive aid for responsible disclosure. It does not assert that any specific unreported OpenEMR endpoint is vulnerable — that must be verified by the reporter on an authorized system before submission.*
