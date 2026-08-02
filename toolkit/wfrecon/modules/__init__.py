"""Recon modules. Each exposes run(client, report, opts)."""
from . import fingerprint, waf, enum_users, exposure, cve_check

ALL = {
    "fingerprint": fingerprint,
    "waf": waf,
    "users": enum_users,
    "exposure": exposure,
    "cve": cve_check,
}
