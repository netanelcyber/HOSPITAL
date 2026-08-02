"""Check for sensitive Wordfence / WordPress files that should not be public.

Wordfence stores logs, config, and scan data under wp-content. Misconfigured
deployments sometimes expose these. This module only performs GET requests and
reports what is readable — it does not download or exfiltrate contents.

Python 3.5 compatible.
"""

from ..report import Finding

# path, severity, why-it-matters
_SENSITIVE = [
    ("wp-content/wflogs/", "high",
     "Wordfence log directory listing exposed (attack data, IPs, config)"),
    ("wp-content/wflogs/config.php", "critical",
     "Wordfence WAF config file readable — may leak keys/rules"),
    ("wp-content/wflogs/rules.php", "high",
     "Wordfence firewall rules readable — reveals bypassable signatures"),
    ("wp-content/wflogs/GeoLite2-Country.mmdb", "low",
     "Wordfence GeoIP DB reachable (confirms wflogs path is browsable)"),
    ("wp-content/plugins/wordfence/readme.txt", "low",
     "Plugin readme exposes exact Wordfence version"),
    ("wp-content/debug.log", "high",
     "WordPress debug log readable — may leak paths, queries, secrets"),
    ("wp-config.php.bak", "critical",
     "Backup of wp-config readable — likely DB credentials"),
    ("wp-config.php~", "critical",
     "Editor backup of wp-config readable — likely DB credentials"),
    (".user.ini", "medium",
     "PHP .user.ini readable — may reveal Wordfence auto_prepend hardening"),
    ("xmlrpc.php", "low",
     "xmlrpc.php reachable — enables pingback/brute-force amplification if not blocked"),
]


def run(client, report, opts):
    for path, sev, why in _SENSITIVE:
        r = client.get(path)
        if r.status == 200 and _has_content(path, r.body):
            report.add(Finding(
                "exposure", sev, "Exposed: /{0}".format(path),
                detail=why,
                evidence="HTTP {0}, {1} bytes".format(r.status, len(r.body)),
            ))

    # Extended Protection check: .user.ini should reference wordfence-waf.php
    r = client.get(".user.ini")
    if r.status == 200 and "wordfence-waf.php" in r.body:
        report.add(Finding(
            "exposure", "info", "Wordfence Extended Protection configured",
            detail="auto_prepend_file points to wordfence-waf.php (firewall runs before "
                   "WordPress loads) — the recommended 'Extended Protection' mode.",
            evidence=".user.ini references wordfence-waf.php",
        ))


def _has_content(path, body):
    # xmlrpc responds 405 to GET normally; a 200 with the XML-RPC banner counts.
    if path.endswith("xmlrpc.php"):
        return "XML-RPC server accepts POST requests only" in body
    # Directory listings / files: any non-trivial body.
    return len(body.strip()) > 0
