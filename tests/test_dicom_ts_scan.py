#!/usr/bin/env python3
"""Tests for dicom_ts_scan against the synthetic corpus in make_samples.py.

Run with `python3 tests/test_dicom_ts_scan.py` or under pytest.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import dicom_ts_scan as scanner  # noqa: E402
from tests import make_samples  # noqa: E402


class ScanTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory()
        cls.root = cls._tmp.name
        make_samples.build(cls.root)
        cls.result = scanner.scan([cls.root], header_bytes=65536, follow_symlinks=False, verbose=False)
        cls.by_name = {os.path.basename(f.path): f for f in cls.result.files}

    @classmethod
    def tearDownClass(cls) -> None:
        cls._tmp.cleanup()

    def test_all_dicom_files_found(self) -> None:
        self.assertEqual(len(self.result.files), 14)
        self.assertEqual(self.result.errors, [])

    def test_non_dicom_is_skipped_not_errored(self) -> None:
        self.assertEqual(self.result.skipped, 1)
        self.assertNotIn("notes.txt", self.by_name)

    def test_transfer_syntax_uids(self) -> None:
        expected = {
            "explicit_le.dcm": "1.2.840.10008.1.2.1",
            "implicit_le.dcm": "1.2.840.10008.1.2",
            "explicit_be.dcm": "1.2.840.10008.1.2.2",
            "j2k_lossless.dcm": "1.2.840.10008.1.2.4.90",
            "j2k_lossy_seq.dcm": "1.2.840.10008.1.2.4.91",
            "htj2k.dcm": "1.2.840.10008.1.2.4.201",
            "jpegls.dcm": "1.2.840.10008.1.2.4.80",
            "jpeg_baseline.dcm": "1.2.840.10008.1.2.4.50",
            "rle.dcm": "1.2.840.10008.1.2.5",
            "private_ts.dcm": "1.2.840.113619.5.2",
        }
        for name, uid in expected.items():
            self.assertEqual(self.by_name[name].transfer_syntax_uid, uid, name)

    def test_modality_from_explicit_vr(self) -> None:
        self.assertEqual(self.by_name["explicit_le.dcm"].modality, "CT")
        self.assertEqual(self.by_name["j2k_lossless.dcm"].modality, "CT")
        self.assertEqual(self.by_name["htj2k.dcm"].modality, "SM")

    def test_modality_from_implicit_vr(self) -> None:
        info = self.by_name["implicit_le.dcm"]
        self.assertEqual(info.modality, "CT")
        self.assertEqual(info.manufacturer, "ACME Imaging")
        self.assertEqual(info.rows, "512")

    def test_big_endian_dataset(self) -> None:
        info = self.by_name["explicit_be.dcm"]
        self.assertEqual(info.modality, "MR")
        self.assertEqual(info.manufacturer, "OldVendor")
        # 1024 read as little endian would come back as 4, not 512.
        self.assertEqual(info.rows, "512")
        self.assertEqual(info.bits_allocated, "16")

    def test_defined_length_sequence_is_skipped(self) -> None:
        info = self.by_name["j2k_lossy_seq.dcm"]
        self.assertEqual(info.modality, "MG")
        self.assertEqual(info.manufacturer, "Mammo Corp")

    def test_undefined_length_sequence_is_skipped(self) -> None:
        info = self.by_name["j2k_undefined_seq.dcm"]
        self.assertEqual(info.modality, "MG")
        # These tags sit *after* the undefined-length sequence, so reading
        # them proves the skip landed on the right byte.
        self.assertEqual(info.manufacturer, "Mammo Corp")
        self.assertEqual(info.rows, "4096")
        self.assertEqual(info.columns, "3328")
        self.assertEqual(info.bits_allocated, "12")

    def test_nested_undefined_length_sequence_is_skipped(self) -> None:
        info = self.by_name["j2k_nested_seq.dcm"]
        self.assertEqual(info.modality, "MG")
        self.assertEqual(info.manufacturer, "Mammo Corp")
        self.assertEqual(info.bits_allocated, "12")

    def test_file_without_preamble(self) -> None:
        info = self.by_name["no_preamble.dcm"]
        self.assertEqual(info.transfer_syntax_uid, "1.2.840.10008.1.2.4.90")
        self.assertEqual(info.modality, "XA")

    def test_unknown_transfer_syntax_is_reported_not_dropped(self) -> None:
        info = self.by_name["private_ts.dcm"]
        self.assertEqual(info.ts_name, "Unknown / private")
        self.assertEqual(info.ts_family, "unknown")

    def test_missing_modality_is_tolerated(self) -> None:
        info = self.by_name["no_modality.dcm"]
        self.assertEqual(info.modality, "")
        self.assertEqual(info.manufacturer, "ACME Imaging")

    def test_family_classification(self) -> None:
        self.assertEqual(self.by_name["j2k_lossless.dcm"].ts_family, "jpeg2000")
        self.assertEqual(self.by_name["htj2k.dcm"].ts_family, "htj2k")
        self.assertEqual(self.by_name["jpegls.dcm"].ts_family, "jpeg-ls")
        self.assertEqual(self.by_name["rle.dcm"].ts_family, "rle")
        self.assertEqual(self.by_name["explicit_le.dcm"].ts_family, "uncompressed")

    def test_sop_class_uid_is_captured(self) -> None:
        self.assertEqual(
            self.by_name["htj2k.dcm"].sop_class_uid, "1.2.840.10008.5.1.4.1.1.77.1.6"
        )

    def test_report_mentions_jpeg2000_share(self) -> None:
        text = scanner.report(self.result)
        self.assertIn("JPEG 2000 family (incl. HTJ2K)", text)
        self.assertIn("Modality x Transfer Syntax", text)

    def _truncated_scan(self, source: str, keep: int) -> scanner.ScanResult:
        with tempfile.TemporaryDirectory() as tmp:
            with open(source, "rb") as fh:
                data = fh.read()
            with open(os.path.join(tmp, "truncated.dcm"), "wb") as fh:
                fh.write(data[:keep])
            return scanner.scan([tmp], 65536, False, False)

    def test_truncation_inside_dataset_still_reports_transfer_syntax(self) -> None:
        # A file cut off partway through the dataset keeps a complete file
        # meta group, so the Transfer Syntax is still recoverable.
        source = os.path.join(self.root, "ct", "explicit_le.dcm")
        with open(source, "rb") as fh:
            meta_end = scanner._parse_meta(fh.read())[1]
        result = self._truncated_scan(source, meta_end + 10)
        self.assertEqual(len(result.files), 1)
        self.assertEqual(result.errors, [])
        self.assertEqual(result.files[0].transfer_syntax_uid, "1.2.840.10008.1.2.1")

    def test_truncation_inside_file_meta_is_skipped_not_crashed(self) -> None:
        # Cut before (0002,0010): there is no Transfer Syntax to report, so
        # the file is skipped rather than guessed at.
        source = os.path.join(self.root, "ct", "explicit_le.dcm")
        result = self._truncated_scan(source, 200)
        self.assertEqual(result.files, [])
        self.assertEqual(result.errors, [])
        self.assertEqual(result.skipped, 1)

    def test_empty_file_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "empty.dcm"), "wb").close()
            result = scanner.scan([tmp], 65536, False, False)
            self.assertEqual(result.files, [])
            self.assertEqual(result.skipped, 1)

    def test_csv_and_json_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = os.path.join(tmp, "out.csv")
            json_path = os.path.join(tmp, "out.json")
            rc = scanner.main([self.root, "--csv", csv_path, "--json", json_path])
            self.assertEqual(rc, 0)
            import csv as csv_mod
            import json as json_mod

            with open(csv_path, encoding="utf-8") as fh:
                rows = list(csv_mod.DictReader(fh))
            self.assertEqual(len(rows), 14)
            with open(json_path, encoding="utf-8") as fh:
                payload = json_mod.load(fh)
            self.assertEqual(payload["summary"]["files"], 14)
            self.assertEqual(payload["summary"]["by_family"]["jpeg2000"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
