# Local Test PACS Setup

Run a standalone DICOM archive locally using **Orthanc** (open-source PACS) to test the scanner, modifier, and upload tools without external systems.

## Prerequisites

- Docker & Docker Compose
- Python 3.9+

## Quick start

```bash
# 1. Start Orthanc
docker-compose up -d

# 2. Verify it's running
curl http://localhost:8042/api/system

# 3. Run the full test workflow
bash test_pacs_workflow.sh
```

The Orthanc web UI runs at **http://localhost:8042** (no login needed for this test config).

## What the workflow does

1. **Generate** 14 synthetic DICOM files covering different Transfer Syntaxes
2. **Upload** them to Orthanc via DICOM REST API
3. **Query** Orthanc for inventory statistics
4. **Download** all instances back as DICOM files
5. **Scan** with `dicom_ts_scan.py` to report Transfer Syntax usage
6. **Modify** copies to declare different syntaxes (for testing viewer handling)
7. **Re-upload** to verify Orthanc accepts them

## Manual commands

### Upload a file
```bash
curl -X POST --data-binary @study.dcm \
  http://localhost:8042/api/instances \
  -H "Content-Type: application/dicom"
```

### List instances
```bash
curl http://localhost:8042/api/instances | jq .
```

### Download an instance
```bash
INSTANCE_ID="abc123"
curl http://localhost:8042/api/instances/$INSTANCE_ID/file \
  -H "Accept: application/dicom" > study.dcm
```

### Query/retrieve (DIMSE protocol)
Orthanc listens on port 4242. Use any DICOM client:
```bash
dcmsend -ae SAMPLE localhost 4242 study.dcm
```

### Statistics
```bash
curl http://localhost:8042/api/statistics | jq .
```

## Teardown

```bash
docker-compose down

# Remove data
docker volume rm hospital_orthanc-data
```

## Orthanc configuration

Edit `orthanc.json` to change:
- `ListenPort` — HTTP port (default 8042)
- `DicomPort` — DIMSE listener port (default 4242)
- `AuthenticationEnabled` — require login
- `RemoteAccessAllowed` — allow non-localhost access
- `Plugins` — add JPEG2000, WebViewer, etc.

After editing, restart:
```bash
docker-compose restart orthanc
```

## Adding plugins

Orthanc has optional plugins for JPEG2000 codec support. To enable:

1. Create a Dockerfile extending `jodogne/orthanc`
2. Install plugin via `orthanc-setup.py`
3. Rebuild and run

See [Orthanc documentation](https://orthanc.uclouvain.be/book/plugins/index.html) for details.

## Integration with scanner tools

Once running, use the tools as normal:

```bash
# Upload via REST API
curl -F "file=@study.dcm" http://localhost:8765/upload

# Or download from Orthanc and scan
curl http://localhost:8042/api/instances/abc123/file \
  -H "Accept: application/dicom" | \
  python3 dicom_ts_scan.py /dev/stdin

# Batch download and scan
mkdir /tmp/orthanc_export
for id in $(curl -s http://localhost:8042/api/instances | jq -r '.[]'); do
  curl -s http://localhost:8042/api/instances/$id/file \
    -H "Accept: application/dicom" > /tmp/orthanc_export/$id.dcm
done
python3 dicom_ts_scan.py /tmp/orthanc_export --csv report.csv
```

## Troubleshooting

**Port 8042 already in use**
```bash
docker-compose down
# Or change in docker-compose.yml: ports: ["9042:8042"]
```

**Orthanc won't start**
```bash
docker-compose logs orthanc
```

**Upload fails with 403**
Check `AuthenticationEnabled` and `RemoteAccessAllowed` in orthanc.json.

**No instances appearing after upload**
Wait a moment (indexing can take a few seconds), then:
```bash
curl http://localhost:8042/api/statistics
```
