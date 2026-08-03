# 🏥 DICOM Lab — Quick Start

## 5 דקות להתחלה

```bash
# 1. בנה מעבדה מלאה (הכל באוטומטי)
bash lab_init.sh /lab

# 2. פתח Orthanc בדפדפן
open http://localhost:8042

# 3. תוצאות
cat /lab/reports/transfer_syntax.csv
cat /lab/reports/benchmark.json | jq .
```

זהו. מעבדה פעילה עם:
- 14 DICOM קבצים
- Orthanc PACS מחובר
- סריקה של Transfer Syntaxes
- בנדצ'מרק של זמנים
- דוחות CSV + JSON

## מה בדיוק קורה?

```
lab_init.sh:
  1. יצור 14 DICOM samples בכל TS שונות
  2. הפעל Orthanc (docker-compose)
  3. העלה לorthanc
  4. הורד בחזרה
  5. סרוק Transfer Syntax
  6. בנדצ'מרק זמנים
  7. בנה test fixtures
```

## הבא — ניסויים

### 1. השוואת גדלי קבצים
```bash
du -sh /lab/source /lab/encoded/j2k_declared
# ראה כמה מקום נשמר
```

### 2. העלה J2K modified
```bash
for f in /lab/encoded/j2k_declared/*.dcm; do
  curl -X POST --data-binary @$f http://localhost:8042/api/instances \
    -H "Content-Type: application/dicom"
done

# הורד וסרוק שוב
python3 dicom_ts_scan.py /lab/downloads_v2 --csv /lab/reports/v2.csv
diff /lab/reports/transfer_syntax.csv /lab/reports/v2.csv
```

### 3. בנדצ'מרק בפועל
```bash
python3 benchmark_decode.py /lab/downloads -v --json /lab/reports/bench_detailed.json
```

### 4. upload server
```bash
python3 dicom_upload_server.py --port 8765

# בעוד terminal:
curl -F "file=@/lab/source/ct/j2k_lossless.dcm" http://localhost:8765/upload | jq .
```

## פתרון בעיות

**Orthanc לא מתחברת?**
```bash
docker-compose logs orthanc
docker-compose down && docker-compose up -d
```

**Port תפוס?**
```bash
# לשנות ב-docker-compose.yml
ports: ["8043:8042"]  # change 8042 → 8043
```

**Python לא מצא את הקבצים?**
```bash
ls /lab/source/
ls /lab/downloads/
```

## Orthanc Web UI

בכתובת `http://localhost:8042`:
- **Patients** — רופאים/מטופלים
- **Studies** — בדיקות
- **Series** — סדרות
- **Instances** — קבצי DICOM

זה ממשק ניהול בסיסי. לצפייה בתמונות בפועל צריך viewer (OHIF, Weasis, וכו').

## קבצים חשובים

| File | Purpose |
| --- | --- |
| `dicom_ts_scan.py` | סרוק TS usage |
| `dicom_modify_ts.py` | שנה tags לבדיקה |
| `benchmark_decode.py` | מדוד זמנים |
| `docker-compose.yml` | Orthanc config |
| `LAB_SETUP.md` | כל הניסויים ורעיונות |
| `PACS_SETUP.md` | Orthanc עמוק יותר |

## התחלה עכשיו!

```bash
bash lab_init.sh /tmp/lab
```

ובו בזמן, קרא LAB_SETUP.md לעוד ניסויים.

---

**כל הכלים בקוד פתוח בשימוש בארה"ב ובאירופה.**
Orthanc + DCMTK + Python = ריפואי מקרוב.
