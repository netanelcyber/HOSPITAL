"""Test WordPress username enumeration vectors that Wordfence is meant to block.

Wordfence Login Security can prevent username enumeration via ?author=N redirects,
the REST users endpoint, and login error message differentiation. This module checks
whether those vectors are open — a direct measure of Wordfence hardening.

Python 3.5 compatible.
"""

import json
import re

from ..report import Finding

_AUTHOR_SLUG = re.compile(r"/author/([^/\"'?]+)", re.I)


def run(client, report, opts):
    open_vectors = []

    # 1) ?author=N redirect leak
    users = []
    for n in range(1, 4):
        r = client.get("?author={0}".format(n), allow_redirects=False)
        loc = r.headers.get("Location", "")
        m = _AUTHOR_SLUG.search(loc) or _AUTHOR_SLUG.search(r.body)
        if m:
            users.append(m.group(1))
    if users:
        open_vectors.append("?author=N redirect")
        report.add(Finding(
            "users", "medium", "Username enumeration via ?author=N",
            detail="Author ID redirects leak login usernames. Wordfence Login Security "
                   "'Prevent user enumeration' is not blocking this.",
            evidence="users: " + ", ".join(sorted(set(users))),
            references=["https://www.wordfence.com/help/login-security/"],
        ))

    # 2) REST API /wp-json/wp/v2/users
    r = client.get("wp-json/wp/v2/users")
    if r.status == 200:
        try:
            data = json.loads(r.body)
            names = [u.get("slug") or u.get("name")
                     for u in data if isinstance(u, dict)]
            if names:
                open_vectors.append("REST /wp/v2/users")
                report.add(Finding(
                    "users", "medium", "Username enumeration via REST API",
                    detail="The /wp-json/wp/v2/users endpoint is publicly readable.",
                    evidence="users: " + ", ".join(str(n) for n in names[:10]),
                ))
        except ValueError:
            pass

    # 3) Login error message differentiation (invalid user vs bad password).
    #    Only a single, benign request per case — no brute forcing.
    r_baduser = _login_probe(client, "definitely_not_a_user_zzz", "x")
    r_badpass = _login_probe(client, "admin", "wrongpassword_zzz")
    if r_baduser and r_badpass and r_baduser != r_badpass:
        open_vectors.append("login error differentiation")
        report.add(Finding(
            "users", "low", "Login errors distinguish valid vs invalid usernames",
            detail="Different error text for unknown user vs wrong password lets an "
                   "attacker confirm valid usernames. Wordfence can mask these.",
            evidence="invalid-user='{0}' vs bad-pass='{1}'".format(
                r_baduser[:40], r_badpass[:40]),
        ))

    if not open_vectors:
        report.add(Finding(
            "users", "info", "Username enumeration vectors appear blocked",
            detail="?author, REST users, and login error differentiation all handled.",
        ))


def _login_probe(client, user, pw):
    data = ("log={0}&pwd={1}&wp-submit=Log+In".format(user, pw)).encode()
    r = client.get("wp-login.php", method="POST", data=data,
                   extra_headers={"Content-Type": "application/x-www-form-urlencoded"})
    m = re.search(r"id=\"login_error\".*?</div>", r.body, re.S)
    if m:
        return re.sub(r"<[^>]+>", "", m.group(0)).strip()
    return None
