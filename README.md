# HOSPITAL

Tools for analyzing DICOM Transfer Syntax usage in medical imaging archives (PACS).

**Quick test:** See [PACS_SETUP.md](PACS_SETUP.md) to run a local Orthanc PACS with `docker-compose` and test the full workflow.

## dicom_ts_scan.py

Reports which DICOM Transfer Syntaxes a directory tree of images actually uses —
turning "does this PACS use JPEG 2000?" from a guess into a measurement.

Vendors publish which Transfer Syntaxes they *support*, which is nearly all of
them. What a given archive *stores* is a configuration detail that is usually
undocumented. The only reliable answer comes from the files themselves, in tag
`(0002,0010)` TransferSyntaxUID.

### Usage

```bash
python3 dicom_ts_scan.py /path/to/dicom
python3 dicom_ts_scan.py /path/to/dicom --csv report.csv --json report.json
```

Options:

| Flag | Meaning |
| --- | --- |
| `--csv FILE` | per-file CSV report |
| `--json FILE` | per-file JSON report plus summary counts |
| `--header-bytes N` | bytes read per file (default 65536) |
| `--follow-symlinks` | follow symlinked directories |
| `-v` | print read errors to stderr |

### Output

Three views: a breakdown by Transfer Syntax, a rollup by codec family
(`jpeg2000`, `htj2k`, `jpeg-ls`, `uncompressed`, …), and a modality ×
Transfer Syntax cross-tab — the one that shows whether compression is applied
uniformly or only to some parts of the archive.

```
By family
  Family        Files  Share
  ------------  -----  -----
  jpeg2000          5  35.7%
  uncompressed      4  28.6%
  ...

JPEG 2000 family (incl. HTJ2K): 6 / 14 files (42.9%)

Modality x Transfer Syntax
  Modality                               Transfer Syntax  Files
  ---------  -------------------------------------------  -----
  CT         JPEG 2000 Image Compression (Lossless Only)      1
  MG                         JPEG 2000 Image Compression      2
```

### Design notes

- **No dependencies.** Python 3.9+ standard library only. Clinical
  workstations rarely permit installing packages, so the DICOM file meta group
  and the few dataset tags needed are parsed directly.
- **PixelData is never read.** Parsing stops at `(7FE0,0010)` or once group
  `0028` is passed, so nothing is decompressed and no image content is
  touched. Only technical metadata is read — no patient identifiers are
  extracted, printed, or written to the reports.
- **Handles the encodings found in real archives:** implicit VR, explicit VR
  little and big endian, encapsulated pixel data, sequences of defined and
  undefined length including nested ones, and files written without the
  128-byte preamble.
- **Unknown UIDs are reported, not dropped** — private Transfer Syntaxes show
  up as `Unknown / private` with their UID intact.
- **Malformed files are skipped, not fatal.** A file with no readable
  `(0002,0010)` is counted as skipped; read errors are collected and counted.

### Transfer Syntaxes recognised

All standard DICOM Transfer Syntaxes, grouped into families:

| Family | Includes |
| --- | --- |
| `uncompressed` | Implicit/Explicit VR LE, Explicit VR BE, Deflated |
| `rle` | RLE Lossless |
| `jpeg` | Baseline, Extended, Lossless (Process 14 and 14 SV1) |
| `jpeg-ls` | JPEG-LS Lossless and Near-Lossless |
| `jpeg2000` | `.4.90`–`.4.95`, including Part 2 multi-component and JPIP |
| `htj2k` | High-Throughput JPEG 2000 `.4.201`–`.4.203` |
| `jpeg-xl` | `.4.110`–`.4.112` |
| `video` | MPEG-2, MPEG-4 AVC/H.264, HEVC/H.265 |

### Tests

```bash
python3 tests/test_dicom_ts_scan.py
```

`tests/make_samples.py` synthesises the corpus at run time — no patient data
is committed. It can also be run standalone to produce sample files:

```bash
python3 tests/make_samples.py /tmp/samples
```

## dicom_modify_ts.py

Rewrite the Transfer Syntax UID tag `(0002,0010)` in DICOM files for testing.

⚠️ **Warning:** Output files will have mismatched metadata (declared syntax ≠ actual pixel data encoding). Use for testing only, not production.

### Usage

```bash
# Convert one file
python3 dicom_modify_ts.py input.dcm --to j2k --output-dir ./out

# Batch convert directory
python3 dicom_modify_ts.py /path/to/dicoms --to htj2k --output-dir ./test-set

# Use UID directly
python3 dicom_modify_ts.py study.dcm --to 1.2.840.10008.1.2.4.201
```

Shorthand syntaxes: `implicit`, `explicit`, `explicit-be`, `rle`, `j2k-loss`, `j2k`, `jpegls`, `jpeg`, `htj2k`

Then scan the output to verify the tag was rewritten:

```bash
python3 dicom_ts_scan.py ./out --csv verify.csv
```

## dicom_upload_server.py

HTTP server that accepts DICOM file uploads and returns a Transfer Syntax report as JSON.

### Usage

```bash
python3 dicom_upload_server.py --host 127.0.0.1 --port 8765
```

Then POST multipart form data with DICOM files:

```bash
curl -F "file=@study.dcm" http://127.0.0.1:8765/upload | jq .
```

Response:

```json
{
  "summary": {
    "files": 1,
    "total_bytes": 472,
    "skipped_non_dicom": 0,
    "errors": 0,
    "by_transfer_syntax": {
      "1.2.840.10008.1.2.4.90": 1
    },
    "by_family": {
      "jpeg2000": 1
    }
  },
  "files": [
    {
      "transfer_syntax_uid": "1.2.840.10008.1.2.4.90",
      "transfer_syntax_name": "JPEG 2000 Image Compression (Lossless Only)",
      "family": "jpeg2000",
      "modality": "CT",
      "manufacturer": "ACME Imaging",
      "rows": "512",
      "columns": "512",
      "bits_allocated": "16",
      "size_bytes": 472
    }
  ]
}
```
