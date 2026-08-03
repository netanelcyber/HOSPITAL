#!/usr/bin/env python3
"""Security audit for DICOM lab — check configurations, CVEs, and best practices.

Run this on YOUR lab setup to identify security issues before production.
This is for authorized testing only on systems you own/operate.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from enum import Enum

# ANSI colors
class Color(Enum):
    RED = "\033[91m"
    YELLOW = "\033[93m"
    GREEN = "\033[92m"
    BLUE = "\033[94m"
    RESET = "\033[0m"

    def format(self, text: str) -> str:
        return f"{self.value}{text}{Color.RESET.value}"


def log_pass(msg: str) -> None:
    print(f"  {Color.GREEN.format('✓')} {msg}")


def log_fail(msg: str) -> None:
    print(f"  {Color.RED.format('✗')} {msg}")


def log_warn(msg: str) -> None:
    print(f"  {Color.YELLOW.format('⚠')} {msg}")


def log_info(msg: str) -> None:
    print(f"  {Color.BLUE.format('ℹ')} {msg}")


@dataclass
class AuditResult:
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    details: list[str] = None

    def __post_init__(self) -> None:
        if self.details is None:
            self.details = []

    def add_pass(self, msg: str) -> None:
        self.passed += 1
        log_pass(msg)

    def add_fail(self, msg: str) -> None:
        self.failed += 1
        log_fail(msg)

    def add_warn(self, msg: str) -> None:
        self.warnings += 1
        log_warn(msg)

    def add_info(self, msg: str) -> None:
        log_info(msg)

    def summary(self) -> str:
        total = self.passed + self.failed + self.warnings
        score = (self.passed / total * 100) if total > 0 else 0
        return (
            f"\n{Color.BLUE.format('Summary')}: "
            f"{Color.GREEN.format(f'✓ {self.passed}')} "
            f"{Color.RED.format(f'✗ {self.failed}')} "
            f"{Color.YELLOW.format(f'⚠ {self.warnings}')} "
            f"Score: {score:.0f}%"
        )


# ============================================================================
# Orthanc Audit
# ============================================================================


def audit_orthanc(orthanc_url: str, orthanc_json: str) -> AuditResult:
    print(f"\n{Color.BLUE.format('Orthanc PACS Security Audit')}")
    print("=" * 60)
    result = AuditResult()

    # 1. Check if running
    print("\n[1] Service Health")
    try:
        with urllib.request.urlopen(f"{orthanc_url}/api/system") as resp:
            data = json.loads(resp.read())
            result.add_pass(f"Orthanc responding (v{data.get('Version', '?')})")
    except urllib.error.URLError:
        result.add_fail("Orthanc not responding")
        return result

    # 2. Check authentication
    print("\n[2] Authentication")
    try:
        with urllib.request.urlopen(f"{orthanc_url}/api/system") as resp:
            if resp.status == 200:
                result.add_warn("Authentication may be disabled (anonymous access)")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            result.add_pass("Authentication enabled (401 Unauthorized)")
        else:
            result.add_warn(f"Unexpected response: {e.code}")

    # 3. Check configuration file
    print("\n[3] Configuration Analysis")
    if os.path.exists(orthanc_json):
        with open(orthanc_json) as f:
            config = json.load(f)

        auth_enabled = config.get("AuthenticationEnabled", False)
        if auth_enabled:
            result.add_pass("AuthenticationEnabled: true")
        else:
            result.add_fail("AuthenticationEnabled: false (CRITICAL)")

        remote_allowed = config.get("RemoteAccessAllowed", True)
        if not remote_allowed:
            result.add_pass("RemoteAccessAllowed: false")
        else:
            result.add_warn("RemoteAccessAllowed: true (exposed to network)")

        users = config.get("RegisteredUsers", {})
        if users:
            result.add_pass(f"RegisteredUsers configured: {len(users)} user(s)")
        elif auth_enabled:
            result.add_warn("AuthenticationEnabled but no RegisteredUsers")
        else:
            result.add_fail("No authentication configured")

        if config.get("HttpCompressionEnabled"):
            result.add_pass("HttpCompressionEnabled: true")

        if config.get("MaximumStorageSize"):
            size_mb = config["MaximumStorageSize"] / (1024 * 1024)
            result.add_pass(f"MaximumStorageSize: {size_mb:.0f} MB")
        else:
            result.add_warn("MaximumStorageSize not configured (unlimited)")

        plugins = config.get("Plugins", [])
        if plugins:
            result.add_info(f"Plugins loaded: {', '.join(plugins)}")
    else:
        result.add_warn(f"orthanc.json not found at {orthanc_json}")

    # 4. Check for known CVEs
    print("\n[4] Known CVEs")
    result.add_info("Manual check required:")
    result.add_info("  - CVE-2025-0896: Auth bypass (< 1.5.8)")
    result.add_info("  - CVE-2026-5437: Out-of-bounds read (< 1.5.9)")
    result.add_info("  - CVE-2026-5440: ZIP DoS (< 1.5.9)")

    return result


# ============================================================================
# Python Code Audit
# ============================================================================


def audit_python_files() -> AuditResult:
    print(f"\n{Color.BLUE.format('Python Code Security Audit')}")
    print("=" * 60)
    result = AuditResult()

    files = [
        "dicom_ts_scan.py",
        "dicom_modify_ts.py",
        "dicom_upload_server.py",
        "benchmark_decode.py",
        "lab_dashboard.py",
    ]

    print("\n[1] Input Validation")
    for fname in files:
        if not os.path.exists(fname):
            continue
        with open(fname) as f:
            content = f.read()

        # Check for open() without validation
        if re.search(r'open\([^)]*request\.[^)]*\)', content):
            result.add_warn(f"{fname}: open() with user input detected")
        else:
            result.add_pass(f"{fname}: No obvious path injection")

        # Check for SQL injection (unlikely in DICOM tools)
        if "sql" in content.lower() and "execute" in content.lower():
            result.add_warn(f"{fname}: SQL detected (check parameterization)")

    print("\n[2] Dependencies")
    deps_to_check = {
        "flask": "Flask web framework",
        "urllib": "Built-in urllib",
        "json": "Built-in json",
    }
    for dep, desc in deps_to_check.items():
        if any(dep in open(f).read() for f in files if os.path.exists(f)):
            result.add_info(f"{desc} used")

    print("\n[3] File Permissions")
    for fname in files:
        if os.path.exists(fname):
            mode = os.stat(fname).st_mode
            if mode & 0o077:
                result.add_warn(f"{fname}: World-readable (mode: {oct(mode)})")
            else:
                result.add_pass(f"{fname}: Restrictive permissions")

    return result


# ============================================================================
# Network & Docker Audit
# ============================================================================


def audit_network() -> AuditResult:
    print(f"\n{Color.BLUE.format('Network & Docker Security Audit')}")
    print("=" * 60)
    result = AuditResult()

    print("\n[1] Docker Compose Configuration")
    if os.path.exists("docker-compose.yml"):
        with open("docker-compose.yml") as f:
            content = f.read()

        if "127.0.0.1:8042" in content:
            result.add_pass("Port 8042 bound to localhost (not exposed)")
        elif "0.0.0.0:8042" in content or ":8042:" in content:
            result.add_warn("Port 8042 may be exposed to network")

        if "orthanc-data" in content or "volume" in content.lower():
            result.add_pass("Data persistence configured")
        else:
            result.add_warn("No volume configuration (data loss on restart)")
    else:
        result.add_warn("docker-compose.yml not found")

    print("\n[2] Network Exposure")
    # Try to connect to common ports
    ports_to_check = [
        (8042, "Orthanc HTTP"),
        (4242, "Orthanc DICOM"),
        (8765, "Upload server"),
        (5000, "Dashboard"),
    ]
    for port, service in ports_to_check:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1):
                result.add_info(f"Port {port} ({service}): Open on localhost")
        except (urllib.error.URLError, TimeoutError):
            result.add_pass(f"Port {port} ({service}): Closed")

    return result


# ============================================================================
# DICOM Security Audit
# ============================================================================


def audit_dicom_parsing() -> AuditResult:
    print(f"\n{Color.BLUE.format('DICOM Parsing Security Audit')}")
    print("=" * 60)
    result = AuditResult()

    if not os.path.exists("dicom_ts_scan.py"):
        result.add_warn("dicom_ts_scan.py not found")
        return result

    with open("dicom_ts_scan.py") as f:
        content = f.read()

    print("\n[1] Buffer Overflow Checks")
    if "len(buf)" in content and "+" in content:
        result.add_pass("Buffer length checks present")
    else:
        result.add_warn("Check for buffer bounds explicitly")

    print("\n[2] Exception Handling")
    if "except" in content and "struct.error" in content:
        result.add_pass("Handles struct parsing errors")
    else:
        result.add_warn("May not handle all parsing exceptions")

    print("\n[3] Denial of Service Protection")
    if "header_bytes" in content and "65536" in content:
        result.add_pass("Limits header parsing to 65KB (DoS mitigation)")
    else:
        result.add_warn("No size limits on parsing")

    print("\n[4] PixelData Handling")
    if "PixelData" in content and "never read" in content:
        result.add_pass("PixelData not decoded (no RCE via codec)")
    else:
        result.add_warn("Verify PixelData is not decompressed")

    return result


# ============================================================================
# Main Audit
# ============================================================================


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Security audit for DICOM lab")
    parser.add_argument(
        "--orthanc-url", default="http://127.0.0.1:8042", help="Orthanc URL"
    )
    parser.add_argument(
        "--orthanc-json", default="./orthanc.json", help="orthanc.json path"
    )
    parser.add_argument("--full", action="store_true", help="Run all audits")
    args = parser.parse_args(argv)

    print(Color.BLUE.format("=" * 60))
    print(Color.BLUE.format("DICOM Lab Security Audit Report"))
    print(Color.BLUE.format("=" * 60))

    results: dict[str, AuditResult] = {}

    # Run audits
    results["Orthanc"] = audit_orthanc(args.orthanc_url, args.orthanc_json)
    results["Python Code"] = audit_python_files()
    results["Network"] = audit_network()
    results["DICOM Parsing"] = audit_dicom_parsing()

    # Summary
    print(f"\n{Color.BLUE.format('=' * 60)}")
    print(Color.BLUE.format("AUDIT SUMMARY"))
    print(Color.BLUE.format("=" * 60))

    total_passed = 0
    total_failed = 0
    total_warnings = 0

    for name, audit in results.items():
        print(f"\n{name}:{audit.summary()}")
        total_passed += audit.passed
        total_failed += audit.failed
        total_warnings += audit.warnings

    # Overall score
    total = total_passed + total_failed + total_warnings
    score = (total_passed / total * 100) if total > 0 else 0

    print(f"\n{Color.BLUE.format('OVERALL SCORE')}: ", end="")
    if score >= 90:
        print(Color.GREEN.format(f"{score:.0f}%"))
    elif score >= 70:
        print(Color.YELLOW.format(f"{score:.0f}%"))
    else:
        print(Color.RED.format(f"{score:.0f}%"))

    # Recommendations
    print(f"\n{Color.BLUE.format('RECOMMENDATIONS')}")
    print("=" * 60)
    if total_failed > 0:
        print(Color.RED.format(f"Fix {total_failed} critical issues before production"))
    if total_warnings > 0:
        print(Color.YELLOW.format(f"Address {total_warnings} warnings"))

    print("\nNext steps:")
    print("  1. Fix all RED (✗) items immediately")
    print("  2. Review YELLOW (⚠) items for your use case")
    print("  3. Enable logging and monitoring")
    print("  4. Set up regular security updates")
    print("  5. Review HIPAA/GDPR compliance requirements")

    return 0 if total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
