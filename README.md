# HOSPITAL

מחקר אבטחת מידע הגנתי בסביבה הביו-רפואית.

## תוכן

- [פרצות אבטחה באפליקציות נפוצות בתחום הביו-רפואי](docs/biomedical-app-vulnerabilities.md) —
  מיפוי חולשות ידועות (CVE-ים פומביים והתראות CISA ICSMA) במערכות PACS/DICOM, EMR/EHR,
  שכבת אינטגרציה HL7/FHIR, ספריות הדמיה רפואית וציוד רפואי מחובר, יחד עם רשימת הקשחה מתועדפת.
- [רשימת חשדות ל-CVE — מועמדים לבדיקה](docs/suspected-cve-candidates.md) —
  השערות הגנתיות (threat-hunting leads) הנגזרות מדפוסי-השורש, עם שיטת אימות, תעדוף,
  ויעדי דיווח (responsible disclosure) לכל מוצר וגוף מתאם. אינה כוללת מזהי CVE אמיתיים או קוד ניצול.
- [תבנית דיווח חולשה — Disclosure Report Template](docs/disclosure-report-template.md) —
  טיוטה מוכנה למילוי לפתיחת advisory פרטי (Title/Version/CWE/Description/Impact/Reproduction/Fix),
  עם דוגמה מלאה ו-checklist טרם הגשה. ללא exploit; דורשת אימות עצמאי לפני שליחה.
