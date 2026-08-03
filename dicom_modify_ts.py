#!/usr/bin/env python3
"""Modify DICOM Transfer Syntax tag (0002,0010) for testing.

Rewrites the TransferSyntaxUID in the file meta group without touching
PixelData. Useful for testing how archives/viewers handle different
declared syntaxes, or for preparing test fixtures.

⚠️  This creates files with mismatched metadata (you tell the decoder one
syntax but give it data in another). Use only for testing, not production.
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
from pathlib import Path

# Maps short names to UIDs
SYNTAXES = {
    "implicit": "1.2.840.10008.1.2",
    "explicit": "1.2.840.10008.1.2.1",
    "explicit-be": "1.2.840.10008.1.2.2",
    "rle": "1.2.840.10008.1.2.5",
    "j2k-loss": "1.2.840.10008.1.2.4.90",
    "j2k": "1.2.840.10008.1.2.4.91",
    "jpegls": "1.2.840.10008.1.2.4.80",
    "jpeg": "1.2.840.10008.1.2.4.50",
    "htj2k": "1.2.840.10008.1.2.4.201",
}


def pad(value: bytes) -> bytes:
    """DICOM strings are even-length."""
    return value + b" " if len(value) % 2 else value


def find_dicm(buf: bytes) -> int:
    """Return offset just past 'DICM' magic."""
    if buf[128:132] == b"DICM":
        return 132
    idx = buf.find(b"DICM", 0, 1024)
    if idx != -1:
        return idx + 4
    raise ValueError("no DICM magic found")


def modify_transfer_syntax(inpath: str, outpath: str, new_uid: str) -> None:
    """Rewrite (0002,0010) TransferSyntaxUID in file meta group."""
    with open(inpath, "rb") as fh:
        buf = fh.read()

    dicm_pos = find_dicm(buf)
    pos = dicm_pos

    # Parse group 0002 to find the old (0002,0010) tag.
    # Group 0002 is always explicit VR little endian.
    found_pos = None
    found_len_pos = None
    found_len_size = None
    old_length = None

    while pos + 8 <= len(buf):
        group, elem = struct.unpack_from("<HH", buf, pos)
        if group != 0x0002:
            break

        pos_tag = pos
        pos += 4
        vr = buf[pos : pos + 2]
        pos += 2

        # Read length
        if vr in {b"OB", b"OW", b"OF", b"OD", b"OL", b"OV", b"SQ", b"UN", b"UT"}:
            pos += 2  # reserved
            (length,) = struct.unpack_from("<I", buf, pos)
            len_pos = pos
            len_size = 4
            pos += 4
        else:
            (length,) = struct.unpack_from("<H", buf, pos)
            len_pos = pos
            len_size = 2
            pos += 2

        if (group, elem) == (0x0002, 0x0010):
            found_pos = pos
            found_len_pos = len_pos
            found_len_size = len_size
            old_length = length
            break

        if length == 0xFFFFFFFF:
            raise ValueError("undefined-length element in group 0002 (unsupported)")

        pos += length

    if found_pos is None:
        raise ValueError("(0002,0010) TransferSyntaxUID not found in file meta group")

    # Build the replacement: reuse the same VR and structure.
    new_value = pad(new_uid.encode())
    old_end = found_pos + old_length

    # Rebuild: everything before found_pos + new length + new value + everything after
    before = buf[:found_len_pos]
    if found_len_size == 2:
        length_bytes = struct.pack("<H", len(new_value))
    else:
        length_bytes = struct.pack("<I", len(new_value))
    after = buf[old_end:]

    result = before + length_bytes + new_value + after

    os.makedirs(os.path.dirname(outpath) or ".", exist_ok=True)
    with open(outpath, "wb") as fh:
        fh.write(result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Rewrite DICOM Transfer Syntax UID for testing.",
        epilog="⚠️  Output files have mismatched metadata. Use for testing only.",
    )
    parser.add_argument("files", nargs="+", help="input DICOM files or directories")
    parser.add_argument(
        "--to",
        required=True,
        help="target Transfer Syntax (UID or shorthand: " + ", ".join(SYNTAXES) + ")",
    )
    parser.add_argument(
        "--output-dir",
        default=".",
        help="output directory (default: current dir)",
    )
    parser.add_argument(
        "--suffix",
        default="_modified",
        help="suffix before .dcm (default: _modified)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    target_uid = SYNTAXES.get(args.to, args.to)
    if not target_uid.startswith("1.2.840.10008"):
        parser.error(f"invalid UID: {target_uid}")

    count = 0
    for file_or_dir in args.files:
        if os.path.isfile(file_or_dir):
            paths = [file_or_dir]
        else:
            paths = list(Path(file_or_dir).rglob("*.dcm"))

        for path in paths:
            try:
                stem = os.path.splitext(os.path.basename(path))[0]
                outname = f"{stem}{args.suffix}.dcm"
                outpath = os.path.join(args.output_dir, outname)
                modify_transfer_syntax(path, outpath, target_uid)
                if args.verbose:
                    print(f"✓ {path} → {outpath} ({target_uid})")
                count += 1
            except (OSError, ValueError) as e:
                print(f"✗ {path}: {e}", file=sys.stderr)
                return 1

    print(f"Modified {count} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
