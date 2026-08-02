# HOSPITAL — Wordfence Recon Toolkit (authorized lab use only)

An automated reconnaissance toolkit for assessing WordPress sites protected by
the **Wordfence** security plugin, plus a self-contained Docker lab to test it
against. Built for **authorized, self-hosted testing** — the CLI refuses
non-local targets unless you explicitly assert authorization.

> ⚠️ **Legal / ethical use only.** Use this exclusively against systems you own
> or have **written permission** to test. Unauthorized scanning is illegal in
> most jurisdictions.

## Layout

```
lab/                 Docker WordPress + Wordfence lab (loopback-only)
  docker-compose.yml
  setup.sh           bring up + install WP, users, Wordfence
  teardown.sh        destroy lab + volumes
toolkit/
  wfrecon.py         launcher (Python 3.5+, stdlib only)
  wfrecon/           package
    modules/         fingerprint, waf, users, exposure, cve
    cve_db.py        local, offline CVE knowledge base
docs/
  METHODOLOGY.md     what each module tests and why
```

## Quick start

```bash
# 1) Spin up the lab (requires Docker)
cd lab && ./setup.sh
#    -> site at http://127.0.0.1:8080

# 2) Run recon against it
cd ../toolkit
python3 wfrecon.py http://127.0.0.1:8080

# JSON output + selected modules
python3 wfrecon.py http://127.0.0.1:8080 -m fingerprint,cve,exposure --json report.json

# 3) Tear down
cd ../lab && ./teardown.sh
```

No pip installs required — the toolkit uses only the Python standard library and
targets **Python 3.5+**.

## Modules

| Module        | What it checks                                                        |
|---------------|-----------------------------------------------------------------------|
| `fingerprint` | Detects Wordfence + parses its version (readme, assets, block page)   |
| `waf`         | Sends benign signature-like probes to see what the firewall blocks    |
| `users`       | Username enumeration via `?author=N`, REST API, login error diffing   |
| `exposure`    | Sensitive files: `wflogs/`, `debug.log`, `wp-config` backups, `.user.ini` |
| `cve`         | Correlates detected plugin versions with a local CVE knowledge base   |

## Safety rail

`wfrecon` resolves the target host and **refuses** anything that is not loopback
or RFC-1918 private, unless you pass `--i-have-authorization`. All probes are
non-destructive GET/POST reconnaissance — no exploitation, no brute forcing, no
data exfiltration.

## Keeping the CVE data fresh

`toolkit/wfrecon/cve_db.py` is a small, hand-curated dataset. Refresh it against:

- Wordfence Intelligence — <https://www.wordfence.com/threat-intel/vulnerabilities>
- NVD — <https://nvd.nist.gov/>
- Patchstack — <https://patchstack.com/database/>

See `docs/METHODOLOGY.md` for details on each check.
