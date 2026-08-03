#!/bin/bash
# Test workflow: generate DICOM → upload to Orthanc → download → scan

set -e

ORTHANC_URL="http://localhost:8042"
ORTHANC_REST="$ORTHANC_URL/api"

echo "=== Test PACS Workflow ==="
echo ""

# 1. Generate sample DICOM files
echo "[1] Generate sample DICOM files..."
python3 tests/make_samples.py /tmp/test_dicoms
echo "    ✓ Generated to /tmp/test_dicoms"
echo ""

# 2. Upload to Orthanc
echo "[2] Upload DICOM files to Orthanc..."
for file in /tmp/test_dicoms/*/*.dcm; do
    echo -n "  uploading $(basename "$file")..."
    curl -s -X POST \
      --data-binary @"$file" \
      "$ORTHANC_REST/instances" \
      -H "Content-Type: application/dicom" \
      > /dev/null
    echo " ✓"
done
echo ""

# 3. Query Orthanc statistics
echo "[3] Orthanc inventory..."
STATS=$(curl -s "$ORTHANC_REST/statistics")
echo "    Patients: $(echo "$STATS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["CountPatients"])')"
echo "    Studies:  $(echo "$STATS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["CountStudies"])')"
echo "    Series:   $(echo "$STATS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["CountSeries"])')"
echo "    Instances: $(echo "$STATS" | python3 -c 'import json,sys; print(json.load(sys.stdin)["CountInstances"])')"
echo ""

# 4. Download all instances
echo "[4] Download instances from Orthanc..."
mkdir -p /tmp/orthanc_download
INSTANCES=$(curl -s "$ORTHANC_REST/instances" | python3 -c 'import json,sys; print(" ".join(json.load(sys.stdin)))')
count=0
for instance_id in $INSTANCES; do
    curl -s "$ORTHANC_REST/instances/$instance_id/file" \
      -H "Accept: application/dicom" \
      > "/tmp/orthanc_download/instance_${instance_id}.dcm"
    count=$((count+1))
done
echo "    ✓ Downloaded $count instances"
echo ""

# 5. Scan downloaded files
echo "[5] Scan Transfer Syntax usage..."
python3 dicom_ts_scan.py /tmp/orthanc_download --csv /tmp/orthanc_download/report.csv --json /tmp/orthanc_download/report.json
echo ""
echo "[6] Export reports"
echo "    CSV:  /tmp/orthanc_download/report.csv"
echo "    JSON: /tmp/orthanc_download/report.json"
echo ""

# 7. Modify and re-upload
echo "[7] Test modifier: create J2K-declared versions..."
python3 dicom_modify_ts.py /tmp/orthanc_download --to j2k --output-dir /tmp/orthanc_j2k --suffix _j2k
echo "    Created in /tmp/orthanc_j2k"
echo "    Scan them:"
echo "      python3 dicom_ts_scan.py /tmp/orthanc_j2k"
echo ""

echo "=== Workflow complete ==="
echo ""
echo "Next steps:"
echo "  1. Inspect Orthanc web UI: http://localhost:8042"
echo "  2. Try uploading modified files:"
echo "     for f in /tmp/orthanc_j2k/*.dcm; do"
echo "       curl -X POST --data-binary @\$f http://localhost:8042/api/instances -H 'Content-Type: application/dicom'"
echo "     done"
echo "  3. Query and download again"
echo "  4. Compare report.json before/after"
