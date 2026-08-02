"""Curated CVE knowledge base for the Wordfence plugin and notable ecosystem
vulnerabilities that a Wordfence-protected site is commonly asked to defend against.

This is a *local, offline* dataset used by the recon toolkit to correlate what it
observes (plugin slug + version) against known issues. It is intentionally small and
hand-curated — refresh it against authoritative sources before relying on it:

  - https://www.wordfence.com/threat-intel/vulnerabilities
  - https://nvd.nist.gov/
  - https://patchstack.com/database/

Version comparisons use "vulnerable if installed < affected_below" semantics via
`version_lt`. Python 3.5 compatible.
"""


class CVE(object):
    def __init__(self, cve, slug, title, severity, affected_below, auth,
                 references=None):
        self.cve = cve
        self.slug = slug            # plugin slug the entry applies to
        self.title = title
        self.severity = severity    # info|low|medium|high|critical
        self.affected_below = affected_below  # vulnerable if version < this
        self.auth = auth            # required privilege
        self.references = references if references is not None else []


# --- Wordfence plugin's own CVEs (defender-tool bugs) -----------------------
WORDFENCE_CVES = [
    CVE(
        "CVE-2022-3144", "wordfence",
        "Wordfence <= 7.6.0 Authenticated (admin) Stored XSS via options page",
        "medium", "7.6.1", "admin",
        ["https://patchstack.com/database/vulnerability/wordfence/"
         "wordpress-wordfence-security-firewall-malware-scan-plugin-7-6-0-"
         "authenticated-stored-cross-site-scripting-xss-vulnerability"],
    ),
    CVE(
        "CVE-2015-XXXX (whoisval)", "wordfence",
        "Wordfence < 5.1.4 Reflected XSS via whoisval parameter (WordfenceWhois)",
        "medium", "5.1.4", "unauthenticated",
        ["https://www.wordfence.com/vulnerability-advisories/"],
    ),
]

# --- Notable ecosystem CVEs worth flagging when the plugin is present -------
# A Wordfence-protected hospital site should be checked for these directly,
# since firewall rules are not a substitute for patching.
ECOSYSTEM_CVES = [
    CVE(
        "CVE-2025-11833", "post-smtp",
        "Post SMTP <= 3.6.0 Unauthenticated account takeover / password reset "
        "(CVSS 9.8, actively exploited)",
        "critical", "3.6.1", "unauthenticated",
        ["https://www.wordfence.com/threat-intel/vulnerabilities",
         "https://www.darkreading.com/vulnerabilities-threats/"
         "critical-site-takeover-flaw-400k-wordpress-sites"],
    ),
]

ALL_CVES = WORDFENCE_CVES + ECOSYSTEM_CVES


def version_lt(installed, fixed_below):
    """Return True if `installed` < `fixed_below` (i.e. still vulnerable)."""
    def norm(v):
        parts = []
        for p in v.split("."):
            num = "".join(ch for ch in p if ch.isdigit())
            parts.append(int(num) if num else 0)
        return parts
    a, b = norm(installed), norm(fixed_below)
    length = max(len(a), len(b))
    a = a + [0] * (length - len(a))
    b = b + [0] * (length - len(b))
    return a < b


def match(slug, version):
    """Yield (cve, confirmed) tuples affecting the given slug/version.
    If version is None, yields all CVEs for the slug as advisory flags."""
    for entry in ALL_CVES:
        if entry.slug != slug:
            continue
        if version is None:
            yield entry, False  # unconfirmed (version unknown)
        elif version_lt(version, entry.affected_below):
            yield entry, True   # confirmed vulnerable by version
