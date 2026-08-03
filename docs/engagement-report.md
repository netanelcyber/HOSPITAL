# דוח סיכום — מחקר אבטחה הגנתי בתחום הביו-רפואי

**תאריך:** אוגוסט 2026
**סוג:** מחקר הגנתי (defensive security research) + אימות מעשי
**היקף:** אפליקציות וספריות נפוצות בסביבת הבריאות — PACS/DICOM, EMR/EHR, HL7/FHIR, ספריות הדמיה, ציוד רפואי מחובר (IoMT)

> מסמך זה מסכם ברמה גבוהה. הפירוט הטכני נמצא במסמכים הייעודיים המפורטים ב-§8. פרטי ממצא לא-מתוקן וה-reproducer **אינם** במסמך זה ואינם ב-repo — הם מוחזקים פרטית ל-disclosure מתואם.

---

## 1. מטרה והיקף

מיפוי הגנתי של חולשות ידועות ומפורסמות במערכות תוכנה נפוצות בבריאות, גזירת השערות לבדיקה (threat-hunting), ואימות מעשי של מחלקת ה-memory-corruption — הכל בהקשר הגנתי, ללא קוד ניצול, ועם תהליך responsible disclosure.

## 2. תוצרים

| תוצר | תיאור |
|---|---|
| `biomedical-app-vulnerabilities.md` | קטלוג CVE-ים מאומתים ב-5 רבדים + דפוסי-שורש + hardening checklist מתועדף |
| `suspected-cve-candidates.md` | 22 מועמדים לבדיקה (SUSP-BIO-01..22) + שיטת אימות + יעדי דיווח + ניתוב CNA |
| `disclosure-report-template.md` | תבנית דיווח מוכנה למילוי (Title/Version/CWE/Impact/Repro/Fix) |
| `israel-relevance.md` | התאמה למשק הבריאות הישראלי + ערוצי דיווח מקומיים |
| `fuzzing/` | סביבת fuzzing מבודדת (Docker) לאימות — 3 harnesses (OpenJPEG, GDCM, CharLS) + build/run/triage + RESULTS/COVERAGE-MATRIX |

## 3. מתודולוגיה

```
מחקר CVE-ים מאומתים  →  זיהוי 5 דפוסי-שורש חוזרים (P1–P5)
   →  גזירת 22 השערות (SUSP-BIO)  →  תעדוף לפי CVSS
   →  אימות מעשי של מחלקת ה-memory-corruption (fuzzing תחת ASan/UBSan)
   →  triage + dedup + אימות על הגרסה האחרונה/master
   →  responsible disclosure (טפסים מוכנים, בלי PoC פומבי)
```

עקרונות שנשמרו: בידוד מלא (Docker, קוד פתוח שנבנה מקומית), אין ניצול פעיל, קלטי crash לעולם לא ב-git, והבחנה כנה בין ממצא מאומת להשערה.

## 4. ממצאים

### 4.1 ממצא memory-safety אמיתי (מוחזק פרטי)
Fuzzing של נתיב ה-JPEG2000 של **GDCM** (דרך seeds של J2K-encapsulated DICOM שנבנו ייעודית) העלה **קריאה מחוץ לתחום (heap OOB read, CWE-125)** ב-parser הכותרות של הקודק.
- **חומרה:** Medium (קריאה → קריסה מוכחת; דליפת heap **לא** מאומתת ללא ניתוח data-flow; לא write/RCE).
- **אימות:** משוחזר על הגרסה האחרונה **ועל master**; שני קלטים עצמאיים.
- **חדשוּת:** plausibly-new — לא תואם CVE ידוע (ה-CVE-ים הידועים באותה ספרייה הם בפונקציות אחרות). **לא מאומת סופית** — ממתין ל-dedup מול תור embargoed של גורם מתאם.
- **סטטוס:** לא פורסם ולא נשלח. דוח disclosure מלא + טפסי CERT/CC/MITRE + מייל למתחזק מוכנים (פרטית).

### 4.2 תוצאות שליליות (חשובות באותה מידה)
- **OpenJPEG** — נקי מ-memory-corruption ברמת כיסוי עמוקה (corpus מגוון, value-profile).
- **CharLS** — אין memory-corruption; **signed-overflow (CWE-190) שנותר פתוח** (לא "שפיר" — ASan לא מאבחן UB אריתמטי) + slow-unit (CPU-DoS).

### 4.3 rediscovery של באג ידוע
- **GDCM allocation-DoS** (163B → 4.29GB) — תואם **CVE-2026-3650**, duplicate, לא דווח.

## 5. הבחנה מתודולוגית מרכזית
מחלקת ה-memory-corruption (CVSS הגבוה, פוטנציאל RCE) הורצה ראשונה בפועל. השאר (ACL/SSTI ב-EMR, HL7/FHIR injection, secrets/רשת) הם **מחלקת-תקיפה שדורשת אפליקציה/רשת חיה** — לא ניתנים ל-fuzzing מקומי, ולא אחראי להקימם מול יעדים אמיתיים. מופו עם שיטת אימות וניתוב דיווח, לביצוע על מערכות בבעלות המשתמש.

## 6. רלוונטיות לישראל
- **שכבת FHIR/HL7** בעדיפות עליונה (חוק ניוד המידע הרפואי, HIE לאומי).
- **GDCM** רלוונטי בישראל בעיקר דרך **pipelines של AI הדמייתי** (pydicom+GDCM) וכלי מחקר (Slicer/Orthanc/ITK) — פחות דרך ה-PACS הקליני הקנייני.
- ערוצי דיווח: CERT-IL (`report@cyber.gov.il` / 119), אגף הסייבר במשרד הבריאות, הרשות להגנת הפרטיות (בכפוף להערכת אירוע).

## 7. המלצות / צעדים הבאים
1. **Dedup סופי** לממצא ה-GDCM מול ה-tracker ותור Talos → אם חדש, disclosure מתואם דרך CERT/CC + CISA.
2. **הרחבת ה-hunt:** seeds אמיתיים ל-B06 (RT-STRUCT), harness ל-B07 (encapsulated PDF, דורש נתיב אחר), FHIRPath ReDoS.
3. **hardening מיידי** לפי ה-checklist המתועדף (Mirth 4.4.1+ קודם — RCE בניצול אקטיבי).
4. אימות מועמדי ה-EMR/FHIR על **מערכות בבעלותכם** בלבד.

## 8. מסמכים מפורטים
`docs/biomedical-app-vulnerabilities.md` · `docs/suspected-cve-candidates.md` · `docs/disclosure-report-template.md` · `docs/israel-relevance.md` · `fuzzing/RESULTS.md` · `fuzzing/COVERAGE-MATRIX.md`

## 9. הצהרת אחריות
כל העבודה הגנתית ולמטרות אבטחה מורשות בלבד. בדיקה של כל מערכת מותרת אך ורק בהרשאה. ממצאים אמיתיים מדווחים ב-responsible disclosure לפני כל פרסום. פרטי חולשות לא-מתוקנות ו-reproducers אינם במאגר זה.
