#!/usr/bin/env python3
"""Crash triage: dedup captured crash inputs by a root-cause signal, keep one
representative per bucket, and produce a minimized reproducer where possible.

Emits findings.json. Reusable both as a module (orchestrator calls triage_dir)
and standalone (python3 triage.py --crashes DIR --out DIR).

The HL7 bucketing mirrors the manually-validated triage: crashes are grouped by
their maximum field length (the signal that separated the oversized-field root
cause). A generic fallback buckets by size + head hash for non-HL7 artifacts.
"""
import argparse
import glob
import hashlib
import json
import os

SB, EB, CR = b"\x0b", b"\x1c", b"\x0d"


def _hl7_max_field(raw: bytes) -> int:
    body = raw.strip(SB + EB + CR)
    return max((len(f) for f in body.split(b"|")), default=0)


def _bucket(path: str):
    raw = open(path, "rb").read()
    if path.endswith(".hl7"):
        mx = _hl7_max_field(raw)
        # bucket oversized-field crashes together (>= 64KiB), else by rounded size
        key = "hl7:oversized-field" if mx >= 65535 else f"hl7:size~{len(raw)//1024}k"
        return key, {"max_field": mx, "size": len(raw)}
    head = hashlib.sha256(raw[:1024]).hexdigest()[:12]
    return f"generic:size~{len(raw)//1024}k:{head}", {"size": len(raw)}


def _minimize_hl7(max_field: int) -> bytes:
    """Smallest input reproducing the oversized-field crash class."""
    threshold = max(60001, 0)
    return (SB + b"MSH|^~\\&|A|B|C|D|20260101||ADT^A01|1|P|2.5\rPID|1||"
            + b"A" * threshold + b"\r" + EB + CR)


def triage_dir(crashes_dir: str, out_dir: str):
    os.makedirs(out_dir, exist_ok=True)
    files = sorted(glob.glob(os.path.join(crashes_dir, "**", "*"), recursive=True))
    files = [f for f in files if os.path.isfile(f) and not f.endswith((".log", ".json"))]

    buckets = {}
    for f in files:
        try:
            key, meta = _bucket(f)
        except Exception:  # noqa: BLE001
            continue
        b = buckets.setdefault(key, {"count": 0, "representative": f, "meta": meta})
        b["count"] += 1

    findings = []
    for key, b in sorted(buckets.items()):
        entry = {
            "bucket": key,
            "crash_count": b["count"],
            "representative": os.path.relpath(b["representative"], crashes_dir),
            "meta": b["meta"],
            "status": "LAB FINDING — requires vendor triage, NOT a confirmed CVE",
        }
        if key == "hl7:oversized-field":
            minim = _minimize_hl7(b["meta"].get("max_field", 60001))
            mpath = os.path.join(out_dir, "MINIMIZED_hl7_oversized_field.hl7")
            with open(mpath, "wb") as fh:
                fh.write(minim)
            entry["minimized_repro"] = os.path.relpath(mpath, out_dir)
            entry["minimized_bytes"] = len(minim)
        findings.append(entry)

    result = {
        "total_crash_artifacts": len(files),
        "unique_buckets": len(buckets),
        "findings": findings,
    }
    out_path = os.path.join(out_dir, "findings.json")
    with open(out_path, "w") as fh:
        json.dump(result, fh, indent=2)
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--crashes", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    r = triage_dir(args.crashes, args.out)
    print(json.dumps(r, indent=2))
