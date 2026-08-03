#!/usr/bin/env python3
"""Web dashboard for DICOM lab — view PACS status, scan results, upload files.

Simple Flask app binding:
- Orthanc API (PACS inventory)
- Scan results (CSV/JSON reports)
- Upload handler (multipart)
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

try:
    from flask import Flask, jsonify, render_template_string, request
except ImportError:
    print("error: flask required. Install with: pip install flask")
    sys.exit(1)

import dicom_ts_scan as scanner

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100MB


def orthanc_api(path: str) -> dict | None:
    """Call Orthanc REST API."""
    try:
        with urllib.request.urlopen(f"http://localhost:8042/api{path}") as resp:
            return json.loads(resp.read())
    except urllib.error.URLError:
        return None


@app.route("/")
def index() -> str:
    """Dashboard home."""
    stats = orthanc_api("/statistics") or {
        "CountPatients": 0,
        "CountStudies": 0,
        "CountSeries": 0,
        "CountInstances": 0,
    }
    return render_template_string(
        """
<!DOCTYPE html>
<html>
<head>
    <title>DICOM Lab Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
               background: #f5f5f5; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        header { background: white; padding: 30px; border-radius: 8px; margin-bottom: 30px;
                 box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h1 { font-size: 32px; margin-bottom: 10px; }
        .subtitle { color: #666; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px; margin-bottom: 30px; }
        .card { background: white; padding: 20px; border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1); text-align: center; }
        .card h3 { color: #666; font-size: 14px; margin-bottom: 10px; }
        .card .value { font-size: 36px; font-weight: bold; color: #2563eb; }
        .section { background: white; padding: 30px; border-radius: 8px;
                   box-shadow: 0 2px 4px rgba(0,0,0,0.1); margin-bottom: 30px; }
        .section h2 { margin-bottom: 20px; font-size: 20px; }
        .upload-box { border: 2px dashed #2563eb; padding: 40px; text-align: center;
                      border-radius: 8px; cursor: pointer; transition: all 0.3s; }
        .upload-box:hover { background: #f0f9ff; }
        input[type="file"] { display: none; }
        button { background: #2563eb; color: white; border: none; padding: 10px 20px;
                border-radius: 6px; cursor: pointer; font-size: 14px; }
        button:hover { background: #1d4ed8; }
        .status-ok { color: #16a34a; }
        .status-error { color: #dc2626; }
        code { background: #f3f4f6; padding: 2px 6px; border-radius: 4px;
               font-family: "Monaco", "Courier New", monospace; }
        .links { display: flex; gap: 20px; }
        a { color: #2563eb; text-decoration: none; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🏥 DICOM Lab Dashboard</h1>
            <p class="subtitle">Local PACS testing environment</p>
            <div class="links">
                <a href="http://localhost:8042" target="_blank">📂 Orthanc PACS</a>
                <a href="/scan">📊 Scan Results</a>
                <a href="/upload">⬆️ Upload</a>
                <a href="/api/status">📡 API Status</a>
            </div>
        </header>

        <div class="grid">
            <div class="card">
                <h3>Patients</h3>
                <div class="value">{{ stats.CountPatients }}</div>
            </div>
            <div class="card">
                <h3>Studies</h3>
                <div class="value">{{ stats.CountStudies }}</div>
            </div>
            <div class="card">
                <h3>Series</h3>
                <div class="value">{{ stats.CountSeries }}</div>
            </div>
            <div class="card">
                <h3>Instances</h3>
                <div class="value">{{ stats.CountInstances }}</div>
            </div>
        </div>

        <div class="section">
            <h2>Quick Actions</h2>
            <p style="margin-bottom: 20px;">
                Initialize lab: <code>bash lab_init.sh /lab</code><br>
                Upload files: use the form below or <code>curl -F "file=@study.dcm" /api/upload</code><br>
                Scan: <code>python3 dicom_ts_scan.py /path --csv report.csv</code>
            </p>
            <div class="upload-box" onclick="document.getElementById('fileInput').click();">
                <p style="margin-bottom: 10px;">📤 Click to upload DICOM files</p>
                <input type="file" id="fileInput" multiple accept=".dcm">
                <div id="uploadStatus"></div>
            </div>
        </div>

        <div class="section">
            <h2>System Status</h2>
            <p>Orthanc: <span id="orthanc-status" class="status-loading">checking...</span></p>
            <p style="font-size: 12px; color: #666; margin-top: 10px;">
                Dashboard running at http://localhost:5000
            </p>
        </div>
    </div>

    <script>
        // Check Orthanc status
        fetch('/api/status')
            .then(r => r.json())
            .then(d => {
                const el = document.getElementById('orthanc-status');
                el.className = d.orthanc ? 'status-ok' : 'status-error';
                el.textContent = d.orthanc ? '✓ Connected' : '✗ Disconnected';
            });

        // File upload
        document.getElementById('fileInput').addEventListener('change', async (e) => {
            const files = e.target.files;
            const status = document.getElementById('uploadStatus');
            status.textContent = 'Uploading...';

            for (const file of files) {
                const fd = new FormData();
                fd.append('file', file);
                try {
                    const r = await fetch('/api/upload', { method: 'POST', body: fd });
                    const d = await r.json();
                    if (r.ok) {
                        status.textContent += '\\n✓ ' + file.name;
                    } else {
                        status.textContent += '\\n✗ ' + file.name + ': ' + d.error;
                    }
                } catch (err) {
                    status.textContent += '\\n✗ ' + file.name + ': ' + err.message;
                }
            }
            location.reload();
        });
    </script>
</body>
</html>
        """,
        stats=stats,
    )


@app.route("/api/status")
def api_status() -> dict:
    """System status."""
    orthanc = orthanc_api("/system") is not None
    return jsonify({"orthanc": orthanc})


@app.route("/api/upload", methods=["POST"])
def api_upload() -> dict:
    """Upload and scan DICOM files."""
    if "file" not in request.files:
        return jsonify({"error": "no file"}), 400

    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        for file in request.files.getlist("file"):
            path = os.path.join(tmpdir, file.filename or "file.dcm")
            file.save(path)
        result = scanner.scan([tmpdir], 65536, False, False)
        return jsonify(
            {
                "files": len(result.files),
                "by_family": dict(
                    __import__("collections").Counter(f.ts_family for f in result.files)
                ),
            }
        )


@app.route("/scan")
def scan_page() -> str:
    """Scan results viewer."""
    reports_dir = "/lab/reports"
    csv_path = os.path.join(reports_dir, "transfer_syntax.csv")
    json_path = os.path.join(reports_dir, "transfer_syntax.json")

    csv_data = None
    json_data = None

    if os.path.exists(csv_path):
        with open(csv_path) as f:
            lines = f.readlines()
            csv_data = "".join(lines[:20])  # First 20 lines

    if os.path.exists(json_path):
        with open(json_path) as f:
            json_data = json.load(f)

    return render_template_string(
        """
<!DOCTYPE html>
<html>
<head>
    <title>Scan Results</title>
    <style>
        body { font-family: monospace; background: #f5f5f5; margin: 20px; }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 { margin-bottom: 20px; }
        .section { background: white; padding: 20px; border-radius: 8px;
                   margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        h2 { font-size: 16px; margin-bottom: 10px; }
        pre { overflow-x: auto; font-size: 12px; }
        a { color: #2563eb; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📊 Scan Results</h1>
        <a href="/">← Back to dashboard</a>

        {% if json_data %}
        <div class="section">
            <h2>Summary</h2>
            <p>Files: {{ json_data.summary.files }}</p>
            <p>Total bytes: {{ json_data.summary.total_bytes }}</p>
        </div>
        {% endif %}

        {% if csv_data %}
        <div class="section">
            <h2>Raw CSV (first 20 lines)</h2>
            <pre>{{ csv_data }}</pre>
            <a href="/lab/reports/transfer_syntax.csv">Download full CSV</a>
        </div>
        {% endif %}

        {% if not csv_data and not json_data %}
        <div class="section">
            <p>No reports found. Run: <code>bash lab_init.sh /lab</code></p>
        </div>
        {% endif %}
    </div>
</body>
</html>
        """,
        csv_data=csv_data,
        json_data=json_data,
    )


@app.route("/upload")
def upload_page() -> str:
    """Upload page."""
    return render_template_string(
        """
<!DOCTYPE html>
<html>
<head>
    <title>Upload DICOM</title>
    <style>
        body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
               background: #f5f5f5; padding: 40px 20px; }
        .container { max-width: 600px; margin: 0 auto; background: white; padding: 40px;
                    border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }
        h1 { margin-bottom: 30px; }
        form { display: flex; flex-direction: column; gap: 20px; }
        input[type="file"] { padding: 10px; border: 2px solid #e5e7eb; border-radius: 6px; }
        button { background: #2563eb; color: white; padding: 12px; border: none;
                border-radius: 6px; cursor: pointer; font-size: 16px; }
        button:hover { background: #1d4ed8; }
        a { color: #2563eb; text-decoration: none; }
    </style>
</head>
<body>
    <div class="container">
        <h1>📤 Upload DICOM Files</h1>
        <a href="/">← Back</a>
        <form action="/api/upload" method="POST" enctype="multipart/form-data">
            <input type="file" name="file" accept=".dcm" multiple required>
            <button type="submit">Upload & Scan</button>
        </form>
    </div>
</body>
</html>
        """
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DICOM Lab Dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args(argv)

    print(f"🌐 Dashboard: http://{args.host}:{args.port}")
    print(f"📂 Orthanc:   http://localhost:8042")
    print()

    app.run(host=args.host, port=args.port, debug=args.debug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
