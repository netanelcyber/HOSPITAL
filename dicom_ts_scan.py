#!/usr/bin/env python3
"""Scan a directory tree of DICOM files and report Transfer Syntax usage.

Answers the practical question "is this PACS actually storing JPEG 2000?"
by reading the value of (0002,0010) TransferSyntaxUID from each file and
cross-tabulating it against modality, manufacturer and stored size.

Deliberately dependency-free: hospital workstations rarely allow installing
pydicom, so this parses the DICOM file meta information group and the small
handful of dataset tags it needs by hand. PixelData is never read, so the
scan stays fast and never decompresses anything.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import struct
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Transfer Syntax catalogue
# ---------------------------------------------------------------------------

# name, family, whether the pixel data is encapsulated (compressed)
TRANSFER_SYNTAXES: dict[str, tuple[str, str, bool]] = {
    "1.2.840.10008.1.2": ("Implicit VR Little Endian", "uncompressed", False),
    "1.2.840.10008.1.2.1": ("Explicit VR Little Endian", "uncompressed", False),
    "1.2.840.10008.1.2.1.99": ("Deflated Explicit VR Little Endian", "deflated", False),
    "1.2.840.10008.1.2.2": ("Explicit VR Big Endian", "uncompressed", False),
    "1.2.840.10008.1.2.5": ("RLE Lossless", "rle", True),
    "1.2.840.10008.1.2.4.50": ("JPEG Baseline (Process 1)", "jpeg", True),
    "1.2.840.10008.1.2.4.51": ("JPEG Extended (Process 2 & 4)", "jpeg", True),
    "1.2.840.10008.1.2.4.57": ("JPEG Lossless, Non-Hierarchical (Process 14)", "jpeg", True),
    "1.2.840.10008.1.2.4.70": ("JPEG Lossless, First-Order Prediction (Process 14 SV1)", "jpeg", True),
    "1.2.840.10008.1.2.4.80": ("JPEG-LS Lossless", "jpeg-ls", True),
    "1.2.840.10008.1.2.4.81": ("JPEG-LS Lossy (Near-Lossless)", "jpeg-ls", True),
    "1.2.840.10008.1.2.4.90": ("JPEG 2000 Image Compression (Lossless Only)", "jpeg2000", True),
    "1.2.840.10008.1.2.4.91": ("JPEG 2000 Image Compression", "jpeg2000", True),
    "1.2.840.10008.1.2.4.92": ("JPEG 2000 Part 2 Multi-component (Lossless Only)", "jpeg2000", True),
    "1.2.840.10008.1.2.4.93": ("JPEG 2000 Part 2 Multi-component", "jpeg2000", True),
    "1.2.840.10008.1.2.4.94": ("JPIP Referenced", "jpeg2000", True),
    "1.2.840.10008.1.2.4.95": ("JPIP Referenced Deflate", "jpeg2000", True),
    "1.2.840.10008.1.2.4.100": ("MPEG2 Main Profile / Main Level", "video", True),
    "1.2.840.10008.1.2.4.101": ("MPEG2 Main Profile / High Level", "video", True),
    "1.2.840.10008.1.2.4.102": ("MPEG-4 AVC/H.264 High Profile / Level 4.1", "video", True),
    "1.2.840.10008.1.2.4.103": ("MPEG-4 AVC/H.264 BD-compatible High Profile", "video", True),
    "1.2.840.10008.1.2.4.104": ("MPEG-4 AVC/H.264 High Profile for 2D video", "video", True),
    "1.2.840.10008.1.2.4.105": ("MPEG-4 AVC/H.264 High Profile for 3D video", "video", True),
    "1.2.840.10008.1.2.4.106": ("MPEG-4 AVC/H.264 Stereo High Profile", "video", True),
    "1.2.840.10008.1.2.4.107": ("HEVC/H.265 Main Profile / Level 5.1", "video", True),
    "1.2.840.10008.1.2.4.108": ("HEVC/H.265 Main 10 Profile / Level 5.1", "video", True),
    "1.2.840.10008.1.2.4.110": ("JPEG XL Lossless", "jpeg-xl", True),
    "1.2.840.10008.1.2.4.111": ("JPEG XL JPEG Recompression", "jpeg-xl", True),
    "1.2.840.10008.1.2.4.112": ("JPEG XL", "jpeg-xl", True),
    "1.2.840.10008.1.2.4.201": ("High-Throughput JPEG 2000 (Lossless Only)", "htj2k", True),
    "1.2.840.10008.1.2.4.202": ("High-Throughput JPEG 2000 RPCL (Lossless Only)", "htj2k", True),
    "1.2.840.10008.1.2.4.203": ("High-Throughput JPEG 2000", "htj2k", True),
}

# Modality is 0008,0060; the rest give useful context in the cross-tab.
WANTED_TAGS = {
    (0x0008, 0x0060): "modality",
    (0x0008, 0x0070): "manufacturer",
    (0x0008, 0x1090): "model",
    (0x0028, 0x0010): "rows",
    (0x0028, 0x0011): "columns",
    (0x0028, 0x0100): "bits_allocated",
}
# Once we are past this group there is nothing left we care about, so parsing
# can stop well before PixelData.
LAST_WANTED_GROUP = 0x0028

PIXEL_DATA = (0x7FE0, 0x0010)
ITEM_DELIM = (0xFFFE, 0xE00D)
SEQ_DELIM = (0xFFFE, 0xE0DD)
ITEM = (0xFFFE, 0xE000)

# VRs whose 32-bit length field follows two reserved bytes.
LONG_VRS = {b"OB", b"OW", b"OF", b"OD", b"OL", b"OV", b"SQ", b"UN", b"UT", b"OC"}
UNDEFINED_LENGTH = 0xFFFFFFFF


class NotDicom(Exception):
    """Raised when a file has no parsable DICOM file meta information."""


@dataclass
class FileInfo:
    path: str
    transfer_syntax_uid: str
    sop_class_uid: str = ""
    size_bytes: int = 0
    modality: str = ""
    manufacturer: str = ""
    model: str = ""
    rows: str = ""
    columns: str = ""
    bits_allocated: str = ""

    @property
    def ts_name(self) -> str:
        return TRANSFER_SYNTAXES.get(
            self.transfer_syntax_uid, ("Unknown / private", "unknown", False)
        )[0]

    @property
    def ts_family(self) -> str:
        return TRANSFER_SYNTAXES.get(
            self.transfer_syntax_uid, ("Unknown / private", "unknown", False)
        )[1]


# ---------------------------------------------------------------------------
# Minimal DICOM parsing
# ---------------------------------------------------------------------------


def _read_tag(buf: bytes, pos: int, little: bool) -> tuple[int, int]:
    fmt = "<HH" if little else ">HH"
    return struct.unpack_from(fmt, buf, pos)


def _decode_text(raw: bytes) -> str:
    # DICOM string VRs are padded with a space or NUL and use a limited
    # character set; latin-1 round-trips every byte so nothing ever raises.
    return raw.decode("latin-1").strip(" \x00")


def _parse_explicit_element(buf: bytes, pos: int, little: bool):
    """Return (group, elem, vr, value_bytes, next_pos) for explicit VR."""
    group, elem = _read_tag(buf, pos, little)
    pos += 4
    if (group, elem) in (ITEM, ITEM_DELIM, SEQ_DELIM):
        # Delimiters carry no VR even inside explicit VR datasets.
        (length,) = struct.unpack_from("<I" if little else ">I", buf, pos)
        return group, elem, b"", b"", pos + 4, length
    vr = buf[pos : pos + 2]
    pos += 2
    if vr in LONG_VRS:
        pos += 2  # reserved
        (length,) = struct.unpack_from("<I" if little else ">I", buf, pos)
        pos += 4
    else:
        (length,) = struct.unpack_from("<H" if little else ">H", buf, pos)
        pos += 2
    if length == UNDEFINED_LENGTH:
        return group, elem, vr, b"", pos, length
    return group, elem, vr, buf[pos : pos + length], pos + length, length


def _parse_implicit_element(buf: bytes, pos: int):
    group, elem = _read_tag(buf, pos, True)
    pos += 4
    (length,) = struct.unpack_from("<I", buf, pos)
    pos += 4
    if length == UNDEFINED_LENGTH:
        return group, elem, b"", b"", pos, length
    return group, elem, b"", buf[pos : pos + length], pos + length, length


def _find_dicm(buf: bytes) -> int:
    """Return the offset just past the 'DICM' magic, or raise NotDicom.

    The standard puts it at offset 132 (128-byte preamble + magic). Files
    written by some archives and by DICOMDIR extraction tools drop the
    preamble, so fall back to a bounded search.
    """
    if buf[128:132] == b"DICM":
        return 132
    idx = buf.find(b"DICM", 0, 1024)
    if idx != -1:
        return idx + 4
    raise NotDicom("no DICM magic")


def _parse_meta(buf: bytes) -> tuple[dict[str, str], int]:
    """Parse group 0002, which is always explicit VR little endian."""
    pos = _find_dicm(buf)
    meta: dict[str, str] = {}
    group_end = None
    while pos + 8 <= len(buf):
        group, elem, _vr, value, next_pos, length = _parse_explicit_element(buf, pos, True)
        if group != 0x0002:
            break
        if (group, elem) == (0x0002, 0x0000) and len(value) == 4:
            (group_length,) = struct.unpack("<I", value)
            group_end = next_pos + group_length
        elif (group, elem) == (0x0002, 0x0002):
            meta["sop_class_uid"] = _decode_text(value)
        elif (group, elem) == (0x0002, 0x0010):
            meta["transfer_syntax_uid"] = _decode_text(value)
        pos = next_pos
        if group_end is not None and pos >= group_end:
            break
        if length == UNDEFINED_LENGTH:
            raise NotDicom("undefined length in file meta group")
    if "transfer_syntax_uid" not in meta:
        raise NotDicom("no (0002,0010) TransferSyntaxUID")
    return meta, pos


def _skip_undefined_length(buf: bytes, pos: int, little: bool, explicit: bool) -> int:
    """Skip an undefined-length sequence or encapsulated element."""
    depth = 1
    while pos + 8 <= len(buf) and depth:
        group, elem = _read_tag(buf, pos, little)
        (length,) = struct.unpack_from("<I" if little else ">I", buf, pos + 4)
        pos += 8
        if (group, elem) == SEQ_DELIM:
            depth -= 1
        elif (group, elem) == ITEM:
            if length == UNDEFINED_LENGTH:
                # Item with undefined length: its contents are parsed inline,
                # terminated by an item delimiter, so nothing to skip here.
                continue
            pos += length
        elif (group, elem) == ITEM_DELIM:
            continue
        else:
            # Not a delimiter: the element belongs to an undefined-length item
            # being parsed inline. Re-read it properly.
            pos -= 8
            if explicit:
                *_rest, pos, length = _parse_explicit_element(buf, pos, little)
            else:
                *_rest, pos, length = _parse_implicit_element(buf, pos)
            if length == UNDEFINED_LENGTH:
                depth += 1
    return pos


def _parse_dataset(buf: bytes, pos: int, ts_uid: str) -> dict[str, str]:
    """Pull the handful of context tags we report on.

    The dataset encoding follows the transfer syntax: implicit VR only for
    1.2.840.10008.1.2, big endian only for .1.2.2, and every compressed
    syntax uses explicit VR little endian for the non-pixel elements.
    """
    explicit = ts_uid != "1.2.840.10008.1.2"
    little = ts_uid != "1.2.840.10008.1.2.2"
    out: dict[str, str] = {}
    while pos + 8 <= len(buf):
        try:
            if explicit:
                group, elem, vr, value, next_pos, length = _parse_explicit_element(buf, pos, little)
            else:
                group, elem, vr, value, next_pos, length = _parse_implicit_element(buf, pos)
        except struct.error:
            break
        if (group, elem) == PIXEL_DATA or group > LAST_WANTED_GROUP:
            break
        if length == UNDEFINED_LENGTH:
            pos = _skip_undefined_length(buf, next_pos, little, explicit)
            continue
        key = WANTED_TAGS.get((group, elem))
        if key:
            if key in ("rows", "columns", "bits_allocated"):
                if len(value) == 2:
                    out[key] = str(struct.unpack("<H" if little else ">H", value)[0])
            else:
                out[key] = _decode_text(value)
        pos = next_pos
        if len(out) == len(WANTED_TAGS):
            break
    return out


def scan_file(path: str, header_bytes: int) -> FileInfo:
    size = os.path.getsize(path)
    with open(path, "rb") as fh:
        buf = fh.read(header_bytes)
    meta, pos = _parse_meta(buf)
    info = FileInfo(
        path=path,
        transfer_syntax_uid=meta["transfer_syntax_uid"],
        sop_class_uid=meta.get("sop_class_uid", ""),
        size_bytes=size,
    )
    if pos < len(buf):
        for key, value in _parse_dataset(buf, pos, info.transfer_syntax_uid).items():
            setattr(info, key, value)
    return info


# ---------------------------------------------------------------------------
# Walking and reporting
# ---------------------------------------------------------------------------


def iter_files(roots: list[str], follow_symlinks: bool):
    for root in roots:
        if os.path.isfile(root):
            yield root
            continue
        for dirpath, _dirnames, filenames in os.walk(root, followlinks=follow_symlinks):
            for name in sorted(filenames):
                yield os.path.join(dirpath, name)


@dataclass
class ScanResult:
    files: list[FileInfo] = field(default_factory=list)
    skipped: int = 0
    errors: list[tuple[str, str]] = field(default_factory=list)


def scan(roots: list[str], header_bytes: int, follow_symlinks: bool, verbose: bool) -> ScanResult:
    result = ScanResult()
    for path in iter_files(roots, follow_symlinks):
        try:
            result.files.append(scan_file(path, header_bytes))
        except NotDicom:
            result.skipped += 1
        except (OSError, struct.error) as exc:
            result.errors.append((path, str(exc)))
            if verbose:
                print(f"error: {path}: {exc}", file=sys.stderr)
    return result


def _human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.1f} TiB"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return "  (none)\n"
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    def fmt(cells: list[str]) -> str:
        parts = [
            cells[i].ljust(widths[i]) if i == 0 else cells[i].rjust(widths[i])
            for i in range(len(cells))
        ]
        return "  " + "  ".join(parts).rstrip()
    lines = [fmt(headers), "  " + "  ".join("-" * w for w in widths)]
    lines.extend(fmt(r) for r in rows)
    return "\n".join(lines) + "\n"


def report(result: ScanResult) -> str:
    files = result.files
    out: list[str] = []
    total = len(files)
    total_bytes = sum(f.size_bytes for f in files)
    out.append("DICOM Transfer Syntax scan")
    out.append("=" * 60)
    out.append(f"DICOM files:  {total}")
    out.append(f"Total size:   {_human(total_bytes)}")
    out.append(f"Non-DICOM skipped: {result.skipped}")
    if result.errors:
        out.append(f"Read errors:  {len(result.errors)}")
    out.append("")
    if not total:
        return "\n".join(out) + "\n"

    by_ts = Counter(f.transfer_syntax_uid for f in files)
    bytes_by_ts: Counter[str] = Counter()
    for f in files:
        bytes_by_ts[f.transfer_syntax_uid] += f.size_bytes

    out.append("By Transfer Syntax")
    rows = []
    for uid, count in by_ts.most_common():
        rows.append([
            TRANSFER_SYNTAXES.get(uid, ("Unknown / private", "", False))[0],
            uid,
            str(count),
            f"{100.0 * count / total:.1f}%",
            _human(bytes_by_ts[uid]),
        ])
    out.append(_table(["Transfer Syntax", "UID", "Files", "Share", "Bytes"], rows))

    by_family = Counter(f.ts_family for f in files)
    out.append("By family")
    rows = [
        [fam, str(cnt), f"{100.0 * cnt / total:.1f}%"]
        for fam, cnt in by_family.most_common()
    ]
    out.append(_table(["Family", "Files", "Share"], rows))

    j2k = sum(c for fam, c in by_family.items() if fam in ("jpeg2000", "htj2k"))
    out.append(
        f"JPEG 2000 family (incl. HTJ2K): {j2k} / {total} files "
        f"({100.0 * j2k / total:.1f}%)"
    )
    out.append("")

    # Modality x transfer syntax cross-tab: the view that actually tells you
    # which parts of the archive are compressed and how.
    cross: dict[str, Counter[str]] = defaultdict(Counter)
    for f in files:
        cross[f.modality or "(unknown)"][f.ts_name] += 1
    out.append("Modality x Transfer Syntax")
    rows = []
    for modality in sorted(cross):
        for ts_name, count in cross[modality].most_common():
            rows.append([modality, ts_name, str(count)])
    out.append(_table(["Modality", "Transfer Syntax", "Files"], rows))

    manufacturers = Counter(f.manufacturer or "(unknown)" for f in files)
    out.append("Manufacturers")
    rows = [[m, str(c)] for m, c in manufacturers.most_common(10)]
    out.append(_table(["Manufacturer", "Files"], rows))
    return "\n".join(out)


CSV_FIELDS = [
    "path",
    "transfer_syntax_uid",
    "transfer_syntax_name",
    "family",
    "sop_class_uid",
    "modality",
    "manufacturer",
    "model",
    "rows",
    "columns",
    "bits_allocated",
    "size_bytes",
]


def _as_row(f: FileInfo) -> dict[str, object]:
    return {
        "path": f.path,
        "transfer_syntax_uid": f.transfer_syntax_uid,
        "transfer_syntax_name": f.ts_name,
        "family": f.ts_family,
        "sop_class_uid": f.sop_class_uid,
        "modality": f.modality,
        "manufacturer": f.manufacturer,
        "model": f.model,
        "rows": f.rows,
        "columns": f.columns,
        "bits_allocated": f.bits_allocated,
        "size_bytes": f.size_bytes,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Report DICOM Transfer Syntax usage across a directory tree.",
        epilog="Reads only file headers; PixelData is never decoded.",
    )
    parser.add_argument("paths", nargs="+", help="files or directories to scan")
    parser.add_argument(
        "--header-bytes",
        type=int,
        default=65536,
        help="bytes read from the start of each file (default: 65536)",
    )
    parser.add_argument("--csv", metavar="FILE", help="write a per-file CSV report")
    parser.add_argument("--json", metavar="FILE", help="write a per-file JSON report")
    parser.add_argument(
        "--follow-symlinks", action="store_true", help="follow symlinked directories"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="print read errors")
    args = parser.parse_args(argv)

    missing = [p for p in args.paths if not os.path.exists(p)]
    if missing:
        parser.error("no such path: " + ", ".join(missing))

    result = scan(args.paths, args.header_bytes, args.follow_symlinks, args.verbose)
    print(report(result))

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
            writer.writeheader()
            for f in result.files:
                writer.writerow(_as_row(f))
        print(f"CSV written to {args.csv}")

    if args.json:
        payload = {
            "summary": {
                "files": len(result.files),
                "total_bytes": sum(f.size_bytes for f in result.files),
                "skipped_non_dicom": result.skipped,
                "errors": len(result.errors),
                "by_transfer_syntax": dict(
                    Counter(f.transfer_syntax_uid for f in result.files)
                ),
                "by_family": dict(Counter(f.ts_family for f in result.files)),
            },
            "files": [_as_row(f) for f in result.files],
        }
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, ensure_ascii=False)
        print(f"JSON written to {args.json}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
