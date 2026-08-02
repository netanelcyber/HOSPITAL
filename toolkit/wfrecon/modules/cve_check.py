"""Correlate detected plugins/versions against the local CVE knowledge base.

For Wordfence itself, uses the version parsed by the fingerprint module. Also
enumerates a small set of high-value plugins (via their readme.txt Stable tag) to
flag actively-exploited ecosystem CVEs such as CVE-2025-11833 (Post SMTP).

Python 3.5 compatible.
"""

import re

from ..report import Finding
from .. import cve_db

_STABLE_TAG = re.compile(r"Stable tag:\s*([0-9][0-9A-Za-z.\-]*)", re.I)

# Plugins to probe for ecosystem CVEs (slug -> readme path).
_WATCH = {
    "post-smtp": "wp-content/plugins/post-smtp/readme.txt",
}


def _plugin_version(client, readme_path):
    r = client.get(readme_path)
    if r.status == 200:
        m = _STABLE_TAG.search(r.body)
        if m:
            return m.group(1)
    return None


def run(client, report, opts):
    # 1) Wordfence itself
    wf_version = opts.get("wordfence_version")
    _emit(report, "wordfence", wf_version)

    # 2) Watched ecosystem plugins
    for slug, readme in _WATCH.items():
        version = _plugin_version(client, readme)
        if version is not None:
            report.add(Finding(
                "cve", "info", "Plugin present: {0} {1}".format(slug, version),
                detail="Detected via {0}.".format(readme),
            ))
            _emit(report, slug, version)


def _emit(report, slug, version):
    for entry, confirmed in cve_db.match(slug, version):
        if confirmed:
            report.add(Finding(
                "cve", entry.severity,
                "{0}: {1}".format(entry.cve, entry.title),
                detail="Installed {0} {1} is < {2} (fixed). Auth required: {3}.".format(
                    slug, version, entry.affected_below, entry.auth),
                evidence="{0} version {1}".format(slug, version),
                references=entry.references,
            ))
        elif version is None:
            report.add(Finding(
                "cve", "info",
                "{0} (unconfirmed — {1} version unknown)".format(entry.cve, slug),
                detail="{0}. Could not confirm version; verify manually. "
                       "Fixed in {1}.".format(entry.title, entry.affected_below),
                references=entry.references,
            ))
