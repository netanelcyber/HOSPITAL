#!/usr/bin/env python3
"""Render findings.json into a human-readable report.md.

Crash counts are labeled as LAB FINDINGS requiring vendor triage — never as
confirmed CVEs. Confirmation and disclosure are separate, deliberate steps.
"""
import argparse
import datetime as dt
import json
import os


def render(findings_path: str, out_md: str, meta: dict | None = None):
    with open(findings_path) as fh:
        data = json.load(fh)
    meta = meta or {}

    lines = []
    lines.append("# Chameleon Fuzzing — Automated Run Report")
    lines.append("")
    lines.append(f"**Generated:** {dt.datetime.now().isoformat(timespec='seconds')}")
    if meta.get("target"):
        lines.append(f"**Target (lab):** {meta['target']}")
    if meta.get("rounds"):
        lines.append(f"**Rounds completed:** {meta['rounds']}")
    if meta.get("surfaces"):
        lines.append(f"**Surfaces run:** {', '.join(meta['surfaces'])}")
    if meta.get("restarts") is not None:
        lines.append(f"**Target auto-restarts:** {meta['restarts']}")
    lines.append("")
    lines.append("> Crash counts below are **lab findings requiring vendor "
                 "triage** — not confirmed CVEs. Reproduce, then disclose to "
                 "Elad Systems via the coordinated-disclosure process.")
    lines.append("")
    lines.append(f"- Total crash artifacts: **{data['total_crash_artifacts']}**")
    lines.append(f"- Unique crash buckets (deduped): **{data['unique_buckets']}**")
    lines.append("")

    if not data["findings"]:
        lines.append("_No crashes captured this run._")
    else:
        lines.append("## Findings (deduped by root-cause signal)")
        lines.append("")
        lines.append("| Bucket | Crashes | Representative | Minimized repro |")
        lines.append("|---|---:|---|---|")
        for f in data["findings"]:
            mr = f.get("minimized_repro", "—")
            if "minimized_bytes" in f:
                mr = f"{mr} ({f['minimized_bytes']} B)"
            lines.append(f"| `{f['bucket']}` | {f['crash_count']} | "
                         f"`{f['representative']}` | {mr} |")
        lines.append("")
        lines.append("### Next steps")
        lines.append("1. Reproduce each bucket's representative against a fresh "
                     "target snapshot in the lab.")
        lines.append("2. Attach a debugger/sanitizer to classify (memory-safety "
                     "vs DoS vs logic).")
        lines.append("3. For a genuine bug, draft the coordinated-disclosure "
                     "report to Elad Systems (vendor first → CVE → publish).")

    os.makedirs(os.path.dirname(out_md) or ".", exist_ok=True)
    with open(out_md, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    return out_md


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--findings", required=True)
    ap.add_argument("--out", default="./out/report.md")
    args = ap.parse_args()
    print("wrote", render(args.findings, args.out))
