# DICOM Transfer Syntax Lab

Setup מלא לבנית מעבדה בדיקה של מערכות PACS וטיפול ב-JPEG2000.

## שכבות המעבדה

```
┌─────────────────────────────────────┐
│   Analysis Layer                    │
│  (dicom_ts_scan, modify, upload)   │
├─────────────────────────────────────┤
│   PACS Layer                        │
│  (Orthanc + variants)               │
├─────────────────────────────────────┤
│   Source Layer                      │
│  (DICOM generators, samples)        │
└─────────────────────────────────────┘
```

## 1. Source Layer — הפקת DICOM

### ייצור סינתטי (כבר יש)
```bash
python3 tests/make_samples.py /lab/samples
```
מייצר 14 קבצים בכל Transfer Syntaxes.

### DICOM מחיי אמת
- הורד מ-myvue.tasmc.org.il (שלך)
- בקש דגימות מבית חולים בדיקה
- שתול Orthanc אחד עם קבוצות קלינייה לדוגמה

### יצירת בדיקות מותאמות
```python
# tests/make_custom_samples.py — הרחב את make_samples.py
# כדי ליצור:
# - גדלים שונים (512x512 עד 4096x3328)
# - מודאליטות שונות (CT, MR, US, XA, SM)
# - עומקי bits שונים (8, 12, 16, 32)
# - רמות דחיסה (lossless vs lossy)
```

## 2. PACS Layer — ריבוי קונפיגורציות

### Orthanc Base (כבר יש)
```bash
docker-compose up -d
```

### Orthanc + JPEG2000 plugin (אופציונלי)
```dockerfile
FROM jodogne/orthanc:latest
RUN apt-get update && apt-get install -y orthanc-plugin-jpeg2k
```

### ריבוי instances בדיקה
```yaml
# docker-compose-lab.yml
services:
  orthanc-native:
    image: jodogne/orthanc
    ports: ["8042:8042"]
    volumes: ["orthanc-native:/var/lib/orthanc/db"]
    
  orthanc-j2k:
    image: orthanc-j2k:latest  # עם plugin
    ports: ["8043:8042"]
    volumes: ["orthanc-j2k:/var/lib/orthanc/db"]
    
  orthanc-jpegls:
    image: orthanc-jpegls:latest
    ports: ["8044:8042"]
    volumes: ["orthanc-jpegls:/var/lib/orthanc/db"]
```

## 3. Analysis Layer — מדידה ובדיקה

### סריקה בסיסית
```bash
python3 dicom_ts_scan.py /path --csv report.csv --json report.json
```

### עלות אחסון
```bash
# בעל מדידה — JPEG2000 vs JPEG-LS vs לא דחוס
python3 dicom_modify_ts.py /lab/samples \
  --to j2k --output-dir /lab/encoded_j2k
  
du -sh /lab/samples /lab/encoded_j2k
# השווה גדלי קבצים
```

### זמנים של פענוח
```bash
# benchmark_decode.py (עוד לא כתוב)
# יעלה ל-bench/:
# - קרא DICOM בכל TS
# - מדוד זמן פענוח
# - עלות CPU
```

### שימוש ברשת
```bash
# test_streaming.py
# JPIP (JPEG 2000 streaming) vs WADO REST
# מדוד throughput, latency, bandwidth
```

## 4. Workflow מלא — בדיקה מקצה לקצה

```bash
#!/bin/bash
LAB=/lab

# 1. ייצור
python3 tests/make_samples.py $LAB/source

# 2. העלאה ל-PACS שונות
for ts in native j2k jpegls; do
  curl -F "file=@$LAB/source/*.dcm" \
    http://localhost:804X/api/instances
done

# 3. הורדה
for port in 8042 8043 8044; do
  mkdir $LAB/download_$port
  # הורד כל instances מ-http://localhost:$port
done

# 4. סריקה
python3 dicom_ts_scan.py $LAB/download_* --csv $LAB/comparison.csv

# 5. ניתוח
python3 scripts/analyze_pacs_encoding.py $LAB/comparison.csv
```

## 5. כלים נוספים לבנות

### `benchmark_decode.py`
```python
# Input: תיקיית DICOM
# Output: JSON עם timing per TS
{
  "1.2.840.10008.1.2.1": {"decode_ms": 145, "cpu_pct": 23},
  "1.2.840.10008.1.2.4.90": {"decode_ms": 287, "cpu_pct": 45},
  "1.2.840.10008.1.2.4.201": {"decode_ms": 89, "cpu_pct": 18},
}
```

### `test_streaming.py`
```python
# JPIP client לבדיקת streaming
# - ROI (region of interest) request
# - תרגום מחוזותי
# - כמו מה שקורה בדפדפן עם J2K
```

### `compare_pacs_configs.py`
```python
# השווה TS בין מכונות שונות
# צור טבלה: Modality x PACS x TS used
# זהה פגמים בהנדסה
```

### `generate_test_set.py`
```python
# בנה קבוצת בדיקה כוללת:
# - גדלים שונים
# - מודאליטות שונות
# - דחיסות שונות
# - cases גבול (מינימום/מקסימום)
```

## 6. מבנה ספריות

```
/lab
├── source/           # DICOM original
├── encoded/
│   ├── j2k/
│   ├── jpegls/
│   └── explicit_le/
├── pacs/
│   ├── orthanc-native/
│   ├── orthanc-j2k/
│   └── orthanc-jpegls/
├── downloads/        # מה שחזר מ-PACS
├── reports/
│   ├── transfer_syntax.csv
│   ├── encoding_comparison.csv
│   ├── decode_benchmark.json
│   └── streaming_test.json
└── scripts/
    ├── benchmark_decode.py
    ├── test_streaming.py
    ├── compare_pacs.py
    └── generate_testset.py
```

## 7. שאלות שתוכל לענות עם המעבדה

- **איזה TS משמש כברירת מחדל?** סרוק את הarcheive
- **כמה משטח נשמר?** השווה גדלי קבצים
- **איך הviewer מטפל בJ2K?** בדוק עם OHIF + Cornerstone
- **האם יש תמיכה בHTJ2K?** סרוק פלט, בדוק זמנים
- **איזה קודק מהיר יותר?** benchmark_decode
- **איזה PACS תומך בJPIP?** test_streaming

## 8. התחלה

```bash
# 1. Clone/pull
git checkout claude/pacs-jpeg2000-windows-gx4uma

# 2. בנה מבנה מעבדה
mkdir -p /lab/{source,encoded,pacs,downloads,reports,scripts}

# 3. התחל Orthanc
docker-compose up -d

# 4. הרץ סקריפט הצינור
bash test_pacs_workflow.sh

# 5. בדוק דוחות
cat /lab/reports/transfer_syntax.csv
```

## הרחבות עתידיות

- [ ] Benchmark עם קבצים גדולים (4K, full-frame)
- [ ] Integration עם OHIF Viewer
- [ ] Test WADO-RS streaming
- [ ] Automated CI pipeline (GitHub Actions)
- [ ] Docker multi-stage build לקודקים שונים
- [ ] Dashboard Grafana לmetrics
