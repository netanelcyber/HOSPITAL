#!/usr/bin/env python3
"""Benchmark DICOM decoding time by Transfer Syntax.

Reads the file meta to identify TS, then measures time to parse the dataset
and report on encoding. Doesn't actually decompress PixelData (just reads
size), but gives a sense of metadata overhead.

For real decode benchmarking, use an actual DICOM codec library.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import dicom_ts_scan as scanner


def benchmark_file(path: str, header_bytes: int) -> dict[str, object]:
    """Time the scan operation on a single file."""
    size = os.path.getsize(path)
    start = time.perf_counter()
    try:
        info = scanner.scan_file(path, header_bytes)
        elapsed = time.perf_counter() - start
        return {
            "ts_uid": info.transfer_syntax_uid,
            "ts_name": info.ts_name,
            "family": info.ts_family,
            "modality": info.modality,
            "size_bytes": size,
            "scan_time_ms": elapsed * 1000,
            "size_per_ms": size / (elapsed * 1000) if elapsed > 0 else 0,
        }
    except Exception as e:
        return {
            "error": str(e),
            "size_bytes": size,
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark DICOM scan performance by Transfer Syntax."
    )
    parser.add_argument("paths", nargs="+", help="files or directories")
    parser.add_argument(
        "--header-bytes", type=int, default=65536, help="bytes read per file"
    )
    parser.add_argument("--json", metavar="FILE", help="output JSON")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    results: dict[str, list[dict]] = defaultdict(list)
    total_time = 0
    total_files = 0

    for file_or_dir in args.paths:
        if os.path.isfile(file_or_dir):
            paths = [file_or_dir]
        else:
            paths = list(Path(file_or_dir).rglob("*.dcm"))

        for path in sorted(paths):
            result = benchmark_file(path, args.header_bytes)
            ts_uid = result.get("ts_uid", "unknown")
            results[ts_uid].append(
                {
                    "file": path,
                    **result,
                }
            )
            total_time += result.get("scan_time_ms", 0)
            total_files += 1
            if args.verbose:
                scan_ms = result.get("scan_time_ms", 0)
                print(f"{path}: {scan_ms:.2f}ms ({result.get('family', '?')})")

    # Aggregate by Transfer Syntax
    by_ts: dict[str, dict[str, object]] = {}
    for ts_uid, files in results.items():
        scans = [f.get("scan_time_ms", 0) for f in files if "error" not in f]
        sizes = [f.get("size_bytes", 0) for f in files if "error" not in f]
        if scans:
            by_ts[ts_uid] = {
                "ts_name": files[0].get("ts_name", "unknown"),
                "family": files[0].get("family", "unknown"),
                "files": len(files),
                "scan_time_ms": {
                    "min": min(scans),
                    "max": max(scans),
                    "mean": sum(scans) / len(scans),
                    "total": sum(scans),
                },
                "size_bytes": {
                    "total": sum(sizes),
                    "mean": sum(sizes) / len(sizes) if sizes else 0,
                },
            }

    payload = {
        "summary": {
            "total_files": total_files,
            "total_scan_time_ms": total_time,
            "avg_scan_time_ms": total_time / total_files if total_files > 0 else 0,
        },
        "by_transfer_syntax": by_ts,
        "files": [f for fs in results.values() for f in fs],
    }

    print("Benchmark results")
    print("=" * 60)
    print(f"Files:        {total_files}")
    print(f"Total time:   {total_time:.2f}ms")
    print(f"Avg per file: {total_time / total_files if total_files > 0 else 0:.2f}ms")
    print()
    print("By Transfer Syntax")
    for ts_uid in sorted(by_ts):
        ts = by_ts[ts_uid]
        print(
            f"  {ts['ts_name']:<50} {ts['files']:>3} files  "
            f"{ts['scan_time_ms']['mean']:>6.2f}ms avg"
        )

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        print(f"\nJSON written to {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
