# Camaleon CMS — Detection & Response Playbook

**Prepared for:** Elad
**Date:** 2026-08-02
**Companion to:** [`chameleon-cve-report.md`](./chameleon-cve-report.md)
**Scope:** Detection logic, IOCs, and response runbooks for the four Camaleon CMS
CVEs — CVE-2024-46986, CVE-2024-46987, CVE-2025-2304, CVE-2026-1776.

> **Read this before you deploy any rule.** These signatures target
> *exploitation of specific Camaleon endpoints*. Tune paths (`/admin/media/...`)
> and the `updated_ajax` route to your actual mount point — Camaleon can be
> mounted under a custom prefix. Every regex below is written to be greppable
> first and SIEM-portable second; translate to your platform's DSL, don't paste
> blindly. **Detections reduce dwell time; they do not replace patching to
> ≥ 2.9.1 + `f54a77e`.**

---

## 0. Quick reference — what each CVE looks like in logs

| CVE | Primary artifact | Where it shows up | Fastest single check |
|---|---|---|---|
| CVE-2024-46986 (file write → RCE) | New `.rb` in `config/initializers/` | Filesystem, git status | `git status --porcelain config/initializers/` |
| CVE-2024-46987 (local file read) | `download_private_file?file=../` | Web access logs | grep for `download_private_file` + `..` |
| CVE-2026-1776 (S3 file read) | Same param, S3 backend | Web logs + CloudTrail | same grep, correlate with S3 GetObject |
| CVE-2025-2304 (priv-esc) | `role`/extra param on `updated_ajax` | Web logs + user table | diff admin count over time |

If you only have time to deploy one thing per CVE, deploy the "Fastest single
check" column and move on.

---

## 1. CVE-2024-46986 — Arbitrary file write → RCE

**Endpoint:** `MediaController#upload` · **Vector:** `folder` parameter traversal
· **Payload:** an uploaded file that lands outside the media root, ideally a
`.rb` file under `config/initializers/`.

### 1.1 Filesystem IOCs (highest confidence)

The RCE fires when a Ruby file is written where Rails auto-loads it. These
directories should contain **only** files tracked in source control:

- `config/initializers/*.rb` — the prize target
- `app/**/*.rb`, `lib/**/*.rb` — secondary autoload paths
- Any `.rb`, `.erb`, or `.rake` under the app root with a recent mtime and no
  git provenance

**Detection — untracked/modified Ruby in initializers (run on host):**

```bash
# Files git doesn't know about, or that differ from HEAD, under initializers
git -C /path/to/app status --porcelain config/initializers/

# Belt-and-suspenders for hosts where the deploy isn't a git checkout:
# any .rb in initializers modified in the last 7 days
find /path/to/app/config/initializers -name '*.rb' -mtime -7 -printf '%TY-%Tm-%Td %p\n'
```

**Baseline + continuous (FIM):** enroll the app root in file-integrity
monitoring (auditd / AIDE / Tripwire / osquery `file_events`). Alert on
**create or modify** of any `*.rb` under `config/`, `app/`, `lib/`.

osquery example:

```sql
-- Requires a file_paths entry watching the app dir, e.g.
--   "camaleon": [ "/path/to/app/config/initializers/%%",
--                 "/path/to/app/app/%%", "/path/to/app/lib/%%" ]
SELECT target_path, action, mtime, uid, sha256
FROM file_events
WHERE category = 'camaleon'
  AND action IN ('CREATED','UPDATED')
  AND target_path LIKE '%.rb';
```

auditd watch:

```
-w /path/to/app/config/initializers -p wa -k camaleon_initializer_write
```

### 1.2 Web-log IOCs

The write happens through the media upload endpoint. Look for upload requests
whose parameters contain traversal, and for uploads of Ruby/script content types.

```
# Access-log regex — upload with traversal in folder param
(POST|PUT)\s+\S*/media/(upload|create)\S*
.*(folder|path)=[^&\s]*(\.\.(/|%2f|%2F|\\|%5c))

# Uploaded filename ending in an executable Rails extension
filename="[^"]+\.(rb|erb|rake|ru)"
```

**High-fidelity correlation:** a `media/upload` POST from a given session,
immediately followed (minutes) by the appearance of a new initializer file, is
a near-certain compromise. If you have both web logs and FIM in one SIEM, make
this a single correlation rule — it has almost no false-positive surface.

### 1.3 Response runbook — CVE-2024-46986

1. **Contain.** Assume RCE. Isolate the host from the network; do **not** reboot
   or restart the app process yet — restart is what *executes* a planted
   initializer. Snapshot memory/disk first if forensics are in scope.
2. **Confirm.** Diff `config/initializers/` (and other autoload paths) against a
   known-good source-control checkout. Any extra or modified `.rb` = confirmed.
3. **Scope.** Identify the uploading session/account from web logs; pivot to
   everything that account did. Check for additional planted files in all
   autoload paths, `public/`, and cron/systemd units.
4. **Eradicate.** Rebuild from a known-good artifact rather than deleting files
   in place — a deferred-execution RCE is easy to under-clean. Upgrade to ≥ 2.8.2.
5. **Rotate.** `config/master.key`, `secret_key_base`, DB creds, and — if cloud —
   the instance's IAM credentials (the process could read them).
6. **Recover.** Restore from a backup predating the first malicious upload.

---

## 2. CVE-2024-46987 & CVE-2026-1776 — Path traversal / arbitrary file read

These two share a payload; they differ only in the storage backend that carries
it. Detect them together at the web tier, then disambiguate at the storage tier.

**Endpoint:** `MediaController#download_private_file` · **Vector:** `file`
parameter traversal.

### 2.1 Web-log IOCs (both CVEs)

```
# Core signature — download_private_file with traversal in any encoding
/media/download_private_file\?.*file=[^&\s]*
   (\.\.(/|%2f|%2F|\\|%5c|%252f)          # ../  encoded once or twice
   |%2e%2e                                 # encoded dots
   |/etc/passwd|/master\.key|\.env|database\.yml|secret)  # known target files
```

**Sensitive-target keywords** worth alerting on regardless of traversal syntax,
because they indicate intent even when the encoding is novel:

```
etc/passwd  ·  config/master.key  ·  config/database.yml  ·  .env
config/credentials  ·  secrets.yml  ·  id_rsa  ·  .aws/credentials
```

**Behavioral signal:** a single authenticated session issuing many
`download_private_file` requests with varying `file` values in a short window =
directory enumeration. Rate/variety on this one endpoint is a strong feature.

### 2.2 Disambiguating 46987 (local) vs 1776 (S3)

- **CVE-2024-46987** — local uploader. Successful reads return **local host
  files**. Correlate a `200` on the traversal request with the app process
  opening `/etc/...` (auditd `open`/`openat` on paths outside the media root by
  the app UID).
- **CVE-2026-1776** — S3 uploader. The traversal resolves against the S3 key
  space / mounted paths. Correlate with **CloudTrail `GetObject`** on keys
  containing `..` or on prefixes outside the media prefix, and with S3
  server-access logs.

auditd (local reads by the app user outside media root):

```
-a always,exit -F arch=b64 -S openat -F uid=<app_uid> -F success=1 -k camaleon_file_read
# then filter events whose path is outside the app's media directory
```

CloudTrail (S3 backend) — pseudo-query:

```
eventSource = s3.amazonaws.com
AND eventName = GetObject
AND ( requestParameters.key CONTAINS '..'
      OR requestParameters.key NOT LIKE '<media-prefix>/%' )
AND userIdentity.arn = '<camaleon-app-role-arn>'
```

### 2.3 Response runbook — path traversal reads

1. **Assess reach.** From access logs, list every `file` value that returned a
   `200`/`206`. That is your **confirmed exfiltration list** — treat every file
   on it as disclosed.
2. **Assume secrets are gone.** If any hit maps to `master.key`, `.env`,
   `database.yml`, credentials, or key material — rotate all of it. Do not wait
   for proof the attacker used it; the read is the proof of exposure.
3. **Cloud pivot check (1776).** If S3-backed and an IAM/creds file was
   readable, review CloudTrail for the leaked principal doing anything after the
   read window. Rotate the IAM credentials and audit for attacker-created IAM
   users/roles/keys.
4. **Patch.** Local: ≥ 2.8.2. S3: **the 2.8.2 fix is not enough** — you need
   commit `f54a77e` (PR #1127). Verify the fix is actually present, not just the
   version number.
5. **Compensating control** until patched: WAF/ALB rule blocking `..`, `%2e`,
   and the sensitive-target keywords on the `download_private_file` route.

---

## 3. CVE-2025-2304 — Mass-assignment privilege escalation

**Endpoint:** `UsersController#updated_ajax` · **Vector:** extra `role` (or other
model) parameter smuggled through `params.permit!` during a profile/password
update.

### 3.1 State-based IOCs (most reliable — detect the *result*)

The exploit is a normal-looking POST; the tell is a user's role changing without
an admin action. **Watch the outcome, not just the request.**

```sql
-- Snapshot admins; alert on any change to the set.
-- Column/table names vary by Camaleon version & DB — adjust to schema.
SELECT id, email, role, updated_at
FROM users
WHERE role IN ('admin','super_admin')
ORDER BY updated_at DESC;
```

Operationalize it:

- **Baseline** the admin/privileged-role user set.
- **Alert** on any INSERT/UPDATE that adds a user to a privileged role.
- **Correlate** each such change with an authorized admin action in the audit
  log. A role elevation with **no corresponding admin-panel user-management
  event** is the signature.
- A `users.role` change whose `updated_at` matches a **self-service profile /
  password update** by that same user is CVE-2025-2304 until proven otherwise.

DB trigger (Postgres example) for real-time alerting:

```sql
CREATE OR REPLACE FUNCTION alert_role_escalation() RETURNS trigger AS $$
BEGIN
  IF NEW.role IN ('admin','super_admin')
     AND (OLD.role IS DISTINCT FROM NEW.role) THEN
    RAISE WARNING 'CAMALEON role escalation: user % -> %', NEW.id, NEW.role;
    -- or INSERT into a security_events table your SIEM tails
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_role_escalation
  AFTER UPDATE OF role ON users
  FOR EACH ROW EXECUTE FUNCTION alert_role_escalation();
```

### 3.2 Web-log IOCs

```
# Request to the vulnerable endpoint carrying an unexpected model param
(POST|PUT|PATCH)\s+\S*updated_ajax
   .*(role|roles|admin|user\[role\]|user%5Brole%5D)=
```

Because the parameter can be any mass-assignable attribute, the endpoint name
plus **any parameter that is not part of the normal profile/password form** is
the broader signal. Baseline the legitimate parameter set for `updated_ajax`,
then alert on anything outside it (`role`, `parent_id`, foreign keys, etc.).

### 3.3 Response runbook — CVE-2025-2304

1. **Enumerate rogue admins.** List privileged users whose elevation has no
   matching admin action. Cross-check `created_at` vs `role`-change time — a
   recently self-registered account that became admin is high-signal.
2. **Contain.** Demote/disable the rogue accounts and kill their sessions.
   **Assume they used the admin access** — this bug is a pivot, so treat it as a
   gateway to CVE-2024-46986 (check §1.1 initializers!) and secret reads.
3. **Scope the chain.** For each rogue admin, pull all activity post-elevation:
   media uploads (→ RCE), `download_private_file` reads (→ secrets), config
   changes, new user creation.
4. **Eradicate & patch.** Upgrade to ≥ 2.9.1 (PR #1109). Then re-verify no
   deferred RCE was planted (§1.4/1.1).
5. **Rotate** anything an admin session could have exposed.
6. **Harden.** Disable open self-registration if the app doesn't require it — it
   removes the cheap entry point to this whole chain.

---

## 4. Deployment checklist

- [ ] FIM/auditd/osquery watching all Rails autoload paths for `.rb` writes (§1.1)
- [ ] Web-log rule: `media/upload` + traversal in `folder` (§1.2)
- [ ] Web-log rule: `download_private_file` + traversal / sensitive keywords (§2.1)
- [ ] Correlation: local file reads outside media root by app UID (§2.2)
- [ ] CloudTrail rule: `GetObject` with `..` or outside media prefix (§2.2) — **S3 only**
- [ ] DB monitor/trigger: privileged-role additions (§3.1)
- [ ] Web-log rule: `updated_ajax` + unexpected params (§3.2)
- [ ] Baselines captured: admin user set, `updated_ajax` legit params, initializer file list
- [ ] WAF compensating controls staged for both traversal routes (§2.3)
- [ ] Verified patch level ≥ 2.9.1 **and** `f54a77e` present (not just version string)

---

## 5. False-positive notes

- **Legitimate media uploads** use `folder` too — the traversal (`..`) is the
  discriminator, not the parameter's presence. Don't alert on `folder=` alone.
- **`download_private_file`** is a normal feature; only traversal syntax or
  sensitive-target keywords should page. Volume/variety from one session is the
  behavioral backstop.
- **Admin role changes** happen legitimately via the admin panel. The rule is
  *elevation without a corresponding admin action* — you need the admin audit
  log joined in, or you'll drown in benign changes.
- **`updated_ajax`** fires on every profile save. Alert on the *unexpected
  parameter*, not the endpoint.

---

## Sources

See the source list in the companion report,
[`chameleon-cve-report.md`](./chameleon-cve-report.md). Endpoint and parameter
names are drawn from the Camaleon advisories:
GHSA-wmjg-vqhv-q5p5 (46986), GHSA-cp65-5m9r-vc2c (46987),
GHSA-rp28-mvq3-wf8j (2304), and GHSA-jw5g-f64p-6x78 (2026-1776).
