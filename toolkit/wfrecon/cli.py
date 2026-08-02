"""wfrecon command-line interface.

Safety rail: by default only loopback / RFC-1918 private targets are allowed.
Testing any other host requires the explicit --i-have-authorization flag AND is
your responsibility to have written permission for.

Python 3.5 compatible.
"""

import argparse
import ipaddress
import socket
import sys
from urllib.parse import urlparse

from .http import Client
from .report import Report
from . import modules


def _is_local(host):
    if host in ("localhost",):
        return True
    try:
        ip = ipaddress.ip_address(socket.gethostbyname(host))
    except (ValueError, socket.gaierror):
        return False
    return ip.is_loopback or ip.is_private


def build_parser():
    p = argparse.ArgumentParser(
        prog="wfrecon",
        description="Wordfence recon toolkit for AUTHORIZED, self-hosted testing.",
    )
    p.add_argument("target", help="Base URL, e.g. http://127.0.0.1:8080")
    p.add_argument("-m", "--modules", default="all",
                   help="comma list: " + ",".join(modules.ALL) + " (default: all)")
    p.add_argument("--json", metavar="FILE", help="write JSON report to FILE")
    p.add_argument("--timeout", type=float, default=10.0)
    p.add_argument("--delay", type=float, default=0.0,
                   help="seconds between requests (be polite)")
    p.add_argument("--no-verify-tls", action="store_true",
                   help="disable TLS verification (lab self-signed certs)")
    p.add_argument("--no-color", action="store_true")
    p.add_argument("--i-have-authorization", action="store_true",
                   help="required to target a non-local host you are authorized to test")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    host = urlparse(args.target).hostname or ""

    if not _is_local(host) and not args.i_have_authorization:
        sys.stderr.write(
            "[!] Refusing non-local target '{0}'.\n"
            "    This toolkit is for authorized, self-hosted testing.\n"
            "    If you have WRITTEN permission to test this host, re-run with "
            "--i-have-authorization.\n".format(host))
        return 2

    if args.modules == "all":
        selected = list(modules.ALL.keys())
    else:
        selected = [m.strip() for m in args.modules.split(",") if m.strip()]
        unknown = [m for m in selected if m not in modules.ALL]
        if unknown:
            sys.stderr.write("[!] Unknown module(s): {0}\n".format(", ".join(unknown)))
            return 2
    # fingerprint should run first so later modules can use its results.
    selected.sort(key=lambda m: 0 if m == "fingerprint" else 1)

    client = Client(args.target, timeout=args.timeout, delay=args.delay,
                    verify_tls=not args.no_verify_tls)
    report = Report(args.target)
    opts = {}

    for name in selected:
        try:
            modules.ALL[name].run(client, report, opts)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write("[!] module '{0}' error: {1}\n".format(name, e))

    print(report.to_console(color=not args.no_color))
    if args.json:
        with open(args.json, "w") as fh:
            fh.write(report.to_json())
        print("[+] JSON report written to {0}".format(args.json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
