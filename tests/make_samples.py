#!/usr/bin/env python3
"""Generate synthetic DICOM files covering the encodings the scanner must handle.

Real patient data cannot be committed, so the test corpus is built here:
implicit VR, explicit VR little and big endian, encapsulated (compressed)
pixel data, nested sequences of both defined and undefined length, and files
without the 128-byte preamble.
"""

from __future__ import annotations

import os
import struct
import sys

LONG_VRS = {b"OB", b"OW", b"OF", b"OD", b"OL", b"OV", b"SQ", b"UN", b"UT"}
UNDEFINED_LENGTH = 0xFFFFFFFF


def pad(value: bytes) -> bytes:
    """DICOM values are even-length; string VRs pad with a space."""
    return value + b" " if len(value) % 2 else value


def explicit(group: int, elem: int, vr: bytes, value: bytes, little: bool = True) -> bytes:
    endian = "<" if little else ">"
    head = struct.pack(f"{endian}HH", group, elem) + vr
    if vr in LONG_VRS:
        return head + b"\x00\x00" + struct.pack(f"{endian}I", len(value)) + value
    return head + struct.pack(f"{endian}H", len(value)) + value


def implicit(group: int, elem: int, value: bytes) -> bytes:
    return struct.pack("<HHI", group, elem, len(value)) + value


def undefined_explicit(group: int, elem: int, vr: bytes, little: bool = True) -> bytes:
    endian = "<" if little else ">"
    return (
        struct.pack(f"{endian}HH", group, elem)
        + vr
        + b"\x00\x00"
        + struct.pack(f"{endian}I", UNDEFINED_LENGTH)
    )


def item(value: bytes) -> bytes:
    return struct.pack("<HHI", 0xFFFE, 0xE000, len(value)) + value


def item_undefined() -> bytes:
    return struct.pack("<HHI", 0xFFFE, 0xE000, UNDEFINED_LENGTH)


ITEM_DELIM = struct.pack("<HHI", 0xFFFE, 0xE00D, 0)
SEQ_DELIM = struct.pack("<HHI", 0xFFFE, 0xE0DD, 0)

SOP_CLASS_CT = "1.2.840.10008.5.1.4.1.1.2"


def file_meta(ts_uid: str, sop_class: str = SOP_CLASS_CT) -> bytes:
    """File meta group 0002 — always explicit VR little endian."""
    body = b"".join([
        explicit(0x0002, 0x0001, b"OB", b"\x00\x01"),
        explicit(0x0002, 0x0002, b"UI", pad(sop_class.encode())),
        explicit(0x0002, 0x0003, b"UI", pad(b"1.2.3.4.5.6.7.8")),
        explicit(0x0002, 0x0010, b"UI", pad(ts_uid.encode())),
        explicit(0x0002, 0x0012, b"UI", pad(b"1.2.276.0.7230010.3.0.3.6.4")),
    ])
    group_length = explicit(0x0002, 0x0000, b"UL", struct.pack("<I", len(body)))
    return group_length + body


def dataset_explicit(modality: str, manufacturer: str, model: str, little: bool = True) -> bytes:
    endian = "<" if little else ">"
    return b"".join([
        explicit(0x0008, 0x0060, b"CS", pad(modality.encode()), little),
        explicit(0x0008, 0x0070, b"LO", pad(manufacturer.encode()), little),
        explicit(0x0008, 0x1090, b"LO", pad(model.encode()), little),
        explicit(0x0028, 0x0002, b"US", struct.pack(f"{endian}H", 1), little),
        explicit(0x0028, 0x0010, b"US", struct.pack(f"{endian}H", 512), little),
        explicit(0x0028, 0x0011, b"US", struct.pack(f"{endian}H", 512), little),
        explicit(0x0028, 0x0100, b"US", struct.pack(f"{endian}H", 16), little),
    ])


def dataset_implicit(modality: str, manufacturer: str, model: str) -> bytes:
    return b"".join([
        implicit(0x0008, 0x0060, pad(modality.encode())),
        implicit(0x0008, 0x0070, pad(manufacturer.encode())),
        implicit(0x0008, 0x1090, pad(model.encode())),
        implicit(0x0028, 0x0002, struct.pack("<H", 1)),
        implicit(0x0028, 0x0010, struct.pack("<H", 512)),
        implicit(0x0028, 0x0011, struct.pack("<H", 512)),
        implicit(0x0028, 0x0100, struct.pack("<H", 16)),
    ])


def defined_length_sequence() -> bytes:
    """A ReferencedImageSequence with an explicit length."""
    inner = explicit(0x0008, 0x1150, b"UI", pad(SOP_CLASS_CT.encode()))
    return explicit(0x0008, 0x1140, b"SQ", item(inner))


def undefined_length_sequence() -> bytes:
    """A sequence and an item that both use undefined length."""
    inner = explicit(0x0008, 0x1150, b"UI", pad(SOP_CLASS_CT.encode()))
    return (
        undefined_explicit(0x0008, 0x1140, b"SQ")
        + item_undefined()
        + inner
        + ITEM_DELIM
        + SEQ_DELIM
    )


def nested_undefined_sequence() -> bytes:
    """A sequence nested inside another, both undefined length."""
    innermost = explicit(0x0008, 0x1150, b"UI", pad(SOP_CLASS_CT.encode()))
    nested = (
        undefined_explicit(0x0008, 0x1199, b"SQ")
        + item_undefined()
        + innermost
        + ITEM_DELIM
        + SEQ_DELIM
    )
    return (
        undefined_explicit(0x0008, 0x1140, b"SQ")
        + item_undefined()
        + nested
        + ITEM_DELIM
        + SEQ_DELIM
    )


def encapsulated_pixel_data(frames: list[bytes]) -> bytes:
    """Compressed PixelData: basic offset table plus one item per frame."""
    body = item(b"")  # empty basic offset table
    for frame in frames:
        body += item(frame + (b"\x00" if len(frame) % 2 else b""))
    return undefined_explicit(0x7FE0, 0x0010, b"OB") + body + SEQ_DELIM


def native_pixel_data(nbytes: int, little: bool = True) -> bytes:
    return explicit(0x7FE0, 0x0010, b"OW", b"\x00" * nbytes, little)


# A JPEG 2000 codestream starts with the SOC/SIZ markers; the scanner never
# decodes it, but using a realistic prefix keeps the fixtures honest.
J2K_CODESTREAM = b"\xff\x4f\xff\x51" + b"\x00" * 60
JPEG_STREAM = b"\xff\xd8\xff\xe0" + b"\x00" * 60


def write(path: str, payload: bytes, preamble: bool = True) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        if preamble:
            fh.write(b"\x00" * 128)
        fh.write(b"DICM")
        fh.write(payload)


def build(outdir: str) -> list[str]:
    written: list[str] = []

    def emit(name: str, payload: bytes, preamble: bool = True) -> None:
        path = os.path.join(outdir, name)
        write(path, payload, preamble)
        written.append(path)

    # Explicit VR little endian, uncompressed — the common on-prem default.
    emit(
        "ct/explicit_le.dcm",
        file_meta("1.2.840.10008.1.2.1")
        + dataset_explicit("CT", "ACME Imaging", "Scanner 5000")
        + native_pixel_data(2048),
    )

    # Implicit VR little endian — legacy modality output.
    emit(
        "ct/implicit_le.dcm",
        file_meta("1.2.840.10008.1.2")
        + dataset_implicit("CT", "ACME Imaging", "Scanner 5000")
        + implicit(0x7FE0, 0x0010, b"\x00" * 2048),
    )

    # Explicit VR big endian — retired, still present in old archives.
    emit(
        "mr/explicit_be.dcm",
        file_meta("1.2.840.10008.1.2.2")
        + dataset_explicit("MR", "OldVendor", "Legacy 1.5T", little=False)
        + native_pixel_data(1024, little=False),
    )

    # JPEG 2000 lossless — the syntax this whole exercise is about.
    emit(
        "ct/j2k_lossless.dcm",
        file_meta("1.2.840.10008.1.2.4.90")
        + dataset_explicit("CT", "ACME Imaging", "Scanner 5000")
        + encapsulated_pixel_data([J2K_CODESTREAM]),
    )

    # JPEG 2000 lossy, with a defined-length sequence before PixelData.
    emit(
        "mg/j2k_lossy_seq.dcm",
        file_meta("1.2.840.10008.1.2.4.91")
        + dataset_explicit("MG", "Mammo Corp", "MammoView")
        + defined_length_sequence()
        + encapsulated_pixel_data([J2K_CODESTREAM, J2K_CODESTREAM]),
    )

    # Undefined-length sequence sitting between the tags we read.
    emit(
        "mg/j2k_undefined_seq.dcm",
        file_meta("1.2.840.10008.1.2.4.90")
        + explicit(0x0008, 0x0060, b"CS", pad(b"MG"))
        + undefined_length_sequence()
        + explicit(0x0008, 0x0070, b"LO", pad(b"Mammo Corp"))
        + explicit(0x0028, 0x0010, b"US", struct.pack("<H", 4096))
        + explicit(0x0028, 0x0011, b"US", struct.pack("<H", 3328))
        + explicit(0x0028, 0x0100, b"US", struct.pack("<H", 12))
        + encapsulated_pixel_data([J2K_CODESTREAM]),
    )

    # Nested undefined-length sequences — the parser's hardest skip case.
    emit(
        "mg/j2k_nested_seq.dcm",
        file_meta("1.2.840.10008.1.2.4.91")
        + explicit(0x0008, 0x0060, b"CS", pad(b"MG"))
        + nested_undefined_sequence()
        + explicit(0x0008, 0x0070, b"LO", pad(b"Mammo Corp"))
        + explicit(0x0028, 0x0100, b"US", struct.pack("<H", 12))
        + encapsulated_pixel_data([J2K_CODESTREAM]),
    )

    # HTJ2K — where new deployments are heading.
    emit(
        "sm/htj2k.dcm",
        file_meta("1.2.840.10008.1.2.4.201", "1.2.840.10008.5.1.4.1.1.77.1.6")
        + dataset_explicit("SM", "Pathology Inc", "SlideScanner")
        + encapsulated_pixel_data([J2K_CODESTREAM]),
    )

    # JPEG-LS and baseline JPEG, for family separation in the report.
    emit(
        "ct/jpegls.dcm",
        file_meta("1.2.840.10008.1.2.4.80")
        + dataset_explicit("CT", "ACME Imaging", "Scanner 5000")
        + encapsulated_pixel_data([JPEG_STREAM]),
    )
    emit(
        "us/jpeg_baseline.dcm",
        file_meta("1.2.840.10008.1.2.4.50")
        + dataset_explicit("US", "Ultra Ltd", "UltraView")
        + encapsulated_pixel_data([JPEG_STREAM]),
    )

    # RLE lossless.
    emit(
        "us/rle.dcm",
        file_meta("1.2.840.10008.1.2.5")
        + dataset_explicit("US", "Ultra Ltd", "UltraView")
        + encapsulated_pixel_data([b"\x00" * 64]),
    )

    # No preamble — DICM appears at offset 0.
    emit(
        "odd/no_preamble.dcm",
        file_meta("1.2.840.10008.1.2.4.90")
        + dataset_explicit("XA", "Angio Systems", "AngioOne")
        + encapsulated_pixel_data([J2K_CODESTREAM]),
        preamble=False,
    )

    # An unregistered private transfer syntax.
    emit(
        "odd/private_ts.dcm",
        file_meta("1.2.840.113619.5.2")
        + dataset_explicit("CT", "Private Vendor", "PrivateBox")
        + native_pixel_data(512),
    )

    # Missing modality — must not break the cross-tab.
    emit(
        "odd/no_modality.dcm",
        file_meta("1.2.840.10008.1.2.1")
        + explicit(0x0008, 0x0070, b"LO", pad(b"ACME Imaging"))
        + native_pixel_data(256),
    )

    # Non-DICOM noise the walker has to skip.
    noise = os.path.join(outdir, "odd/notes.txt")
    os.makedirs(os.path.dirname(noise), exist_ok=True)
    with open(noise, "wb") as fh:
        fh.write(b"this is not a DICOM file\n")

    return written


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "samples"
    paths = build(target)
    print(f"wrote {len(paths)} DICOM files to {target}")
