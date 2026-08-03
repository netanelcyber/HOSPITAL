#!/usr/bin/env python3
"""Minimal HTTP server that accepts DICOM file uploads and scans them.

POST multipart form data with files to /upload — returns JSON report of
Transfer Syntax usage.
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import sys
import tempfile
import urllib.parse
from io import BytesIO

import dicom_ts_scan as scanner


class UploadHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/upload":
            self.error(404, "not found")
            return

        content_length = int(self.headers.get("content-length", 0))
        if content_length == 0:
            self.error(400, "content-length required")
            return

        content_type = self.headers.get("content-type", "")
        if not content_type.startswith("multipart/form-data"):
            self.error(400, "multipart/form-data required")
            return

        # Parse boundary
        boundary = None
        for part in content_type.split(";"):
            if part.strip().startswith("boundary="):
                boundary = part.split("=", 1)[1].strip('"')
                break
        if not boundary:
            self.error(400, "no boundary in content-type")
            return

        body = self.rfile.read(content_length)
        with tempfile.TemporaryDirectory() as tmpdir:
            count = self._parse_multipart(body, boundary, tmpdir)
            if count == 0:
                self.error(400, "no files uploaded")
                return
            result = scanner.scan([tmpdir], 65536, False, False)
            self._respond_json(result)

    def _parse_multipart(self, body: bytes, boundary: str, tmpdir: str) -> int:
        count = 0
        parts = body.split(f"--{boundary}".encode())
        for part in parts[1:-1]:
            if not part or part == b"--\r\n" or part == b"--":
                continue
            lines = part.split(b"\r\n", 1)
            if len(lines) < 2:
                continue
            headers_blob, content = lines[0] + b"\r\n" + lines[1], b""
            if len(lines) > 1:
                content = lines[1]
            # Find empty line separating headers from content
            if b"\r\n\r\n" in content:
                headers_part, body_part = content.split(b"\r\n\r\n", 1)
                headers_blob = lines[0] + b"\r\n" + headers_part
                content = body_part
            else:
                continue
            # Strip trailing \r\n
            if content.endswith(b"\r\n"):
                content = content[:-2]
            # Extract filename
            filename = None
            for line in headers_blob.split(b"\r\n"):
                if b"filename=" in line:
                    # Content-Disposition: form-data; name="file"; filename="study.dcm"
                    parts_list = line.split(b'filename="')
                    if len(parts_list) > 1:
                        filename = parts_list[1].split(b'"')[0].decode("utf-8", errors="replace")
                    break
            if not filename:
                filename = f"upload_{count}"
            if not filename.endswith(".dcm"):
                filename += ".dcm"
            filepath = os.path.join(tmpdir, filename)
            with open(filepath, "wb") as fh:
                fh.write(content)
            count += 1
        return count

    def _respond_json(self, result: scanner.ScanResult) -> None:
        payload = {
            "summary": {
                "files": len(result.files),
                "total_bytes": sum(f.size_bytes for f in result.files),
                "skipped_non_dicom": result.skipped,
                "errors": len(result.errors),
                "by_transfer_syntax": dict(
                    __import__("collections").Counter(f.transfer_syntax_uid for f in result.files)
                ),
                "by_family": dict(__import__("collections").Counter(f.ts_family for f in result.files)),
            },
            "files": [
                {
                    "transfer_syntax_uid": f.transfer_syntax_uid,
                    "transfer_syntax_name": f.ts_name,
                    "family": f.ts_family,
                    "modality": f.modality,
                    "manufacturer": f.manufacturer,
                    "rows": f.rows,
                    "columns": f.columns,
                    "bits_allocated": f.bits_allocated,
                    "size_bytes": f.size_bytes,
                }
                for f in result.files
            ],
        }
        self.send_response(200)
        self.send_header("content-type", "application/json")
        body = json.dumps(payload, indent=2).encode()
        self.send_header("content-length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def error(self, code: int, message: str) -> None:
        self.send_response(code)
        self.send_header("content-type", "application/json")
        body = json.dumps({"error": message}).encode()
        self.send_header("content-length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        print(f"{self.client_address[0]} - {format % args}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="HTTP server for DICOM file upload and Transfer Syntax scanning."
    )
    parser.add_argument("--host", default="127.0.0.1", help="bind address (default 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="bind port (default 8765)")
    args = parser.parse_args(argv)

    server = http.server.HTTPServer((args.host, args.port), UploadHandler)
    print(f"listening on http://{args.host}:{args.port}/upload")
    print("POST multipart files to /upload")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nshutdown")
        return 0


if __name__ == "__main__":
    sys.exit(main())
