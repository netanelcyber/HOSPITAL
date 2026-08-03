#!/bin/bash
# Lab initialization — set up everything in one command

set -e

LAB_DIR="${1:-.}"
mkdir -p "$LAB_DIR"/{source,encoded,pacs,downloads,reports,scripts}

echo "🏥 DICOM Lab Initialization"
echo "════════════════════════════════════════════════"
echo ""

# 1. Generate samples
echo "📊 Generating synthetic DICOM corpus..."
python3 tests/make_samples.py "$LAB_DIR/source"
echo "   ✓ Generated to $LAB_DIR/source"
echo ""

# 2. Start Orthanc
echo "🗂️  Starting Orthanc PACS..."
docker compose up -d
sleep 3
if curl -s http://localhost:8042/api/system > /dev/null; then
    echo "   ✓ Orthanc running at http://localhost:8042"
else
    echo "   ✗ Orthanc failed to start"
    exit 1
fi
echo ""

# 3. Upload samples
echo "⬆️  Uploading DICOM files to Orthanc..."
count=0
for file in "$LAB_DIR/source"/*/*.dcm; do
    curl -s -X POST \
        --data-binary @"$file" \
        http://localhost:8042/api/instances \
        -H "Content-Type: application/dicom" > /dev/null
    count=$((count + 1))
done
echo "   ✓ Uploaded $count files"
echo ""

# 4. Download back
echo "⬇️  Downloading from Orthanc..."
mkdir -p "$LAB_DIR/downloads"
INSTANCES=$(curl -s http://localhost:8042/api/instances)
if [ "$INSTANCES" != "[]" ]; then
    python3 -c "
import json, urllib.request
instances = json.loads('$INSTANCES')
for i, iid in enumerate(instances):
    url = f'http://localhost:8042/api/instances/{iid}/file'
    with urllib.request.urlopen(url) as resp:
        with open('$LAB_DIR/downloads/{}.dcm'.format(iid), 'wb') as f:
            f.write(resp.read())
    print(f'  {i+1}. {iid}', end='\r')
print()
"
    echo "   ✓ Downloaded all instances"
else
    echo "   ⚠️  No instances found (retry in a moment)"
fi
echo ""

# 5. Scan
echo "🔍 Scanning Transfer Syntax usage..."
python3 dicom_ts_scan.py "$LAB_DIR/downloads" \
    --csv "$LAB_DIR/reports/transfer_syntax.csv" \
    --json "$LAB_DIR/reports/transfer_syntax.json" > /dev/null
echo "   ✓ Report: $LAB_DIR/reports/transfer_syntax.csv"
echo ""

# 6. Benchmark
echo "⏱️  Benchmarking..."
python3 benchmark_decode.py "$LAB_DIR/downloads" \
    --json "$LAB_DIR/reports/benchmark.json" > /dev/null
echo "   ✓ Report: $LAB_DIR/reports/benchmark.json"
echo ""

# 7. Create test fixtures
echo "🧪 Creating test fixtures..."
python3 dicom_modify_ts.py "$LAB_DIR/source" \
    --to j2k --output-dir "$LAB_DIR/encoded/j2k_declared" \
    --suffix _j2k > /dev/null 2>&1 || true
python3 dicom_modify_ts.py "$LAB_DIR/source" \
    --to htj2k --output-dir "$LAB_DIR/encoded/htj2k_declared" \
    --suffix _htj2k > /dev/null 2>&1 || true
echo "   ✓ Test fixtures in $LAB_DIR/encoded/"
echo ""

echo "════════════════════════════════════════════════"
echo "✅ Lab ready!"
echo ""
echo "📂 Lab structure:"
echo "   $LAB_DIR/"
echo "   ├── source/          (original DICOM)"
echo "   ├── downloads/       (from Orthanc)"
echo "   ├── encoded/         (test fixtures)"
echo "   └── reports/         (scan + benchmark results)"
echo ""
echo "🌐 Orthanc: http://localhost:8042"
echo ""
echo "📖 Next steps:"
echo "   1. Check reports:"
echo "      cat $LAB_DIR/reports/transfer_syntax.csv"
echo "      cat $LAB_DIR/reports/benchmark.json | jq ."
echo ""
echo "   2. Upload modified files:"
echo "      for f in $LAB_DIR/encoded/j2k_declared/*.dcm; do"
echo "        curl -X POST --data-binary @\$f http://localhost:8042/api/instances \\"
echo "          -H 'Content-Type: application/dicom'"
echo "      done"
echo ""
echo "   3. Re-scan and compare:"
echo "      python3 dicom_ts_scan.py /path/to/downloads --csv new_report.csv"
echo ""
echo "   4. Read LAB_SETUP.md for more experiments"
echo ""
