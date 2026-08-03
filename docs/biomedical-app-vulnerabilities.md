# פרצות אבטחה באפליקציות נפוצות בתחום הביו-רפואי

**עודכן:** אוגוסט 2026
**מטרה:** מסמך ייחוס הגנתי (defensive) — מיפוי חולשות ידועות ומפורסמות במערכות תוכנה נפוצות בסביבה הרפואית, לצורך הערכת סיכונים, תעדוף עדכונים והקשחה. כל המידע כאן מבוסס על CVE-ים פומביים, התראות CISA ומחקרים שפורסמו.

> ⚠️ המסמך אינו כולל קוד ניצול (exploit). השימוש המיועד הוא בדיקות מורשות בלבד, ניהול פגיעויות, והגנה על מערכות שבבעלותכם.

---

## 1. תקציר מנהלים

שטח התקיפה של סביבה רפואית מתחלק לחמישה רבדים, ובכולם התגלו ב-2025–2026 חולשות קריטיות:

| רובד | דוגמאות מוצרים | סיכון עיקרי |
|---|---|---|
| PACS / שרתי DICOM | Orthanc, Santesoft Sante PACS, dcm4chee | RCE, גניבת אישורים, HL7→XSS, גישה לא-מאומתת |
| EMR / EHR | OpenEMR, OpenMRS | SQL Injection, SSTI→RCE, Broken Access Control, דליפת PHI |
| אינטגרציה (Interoperability) | Mirth Connect, HAPI FHIR | RCE לא-מאומת, SSRF→גניבת טוקנים, XXE, DoS |
| ספריות וצפיינים לתמונות | GDCM, DCMTK, pydicom/pynetdicom, MicroDicom, RadiAnt, OHIF | Memory corruption, Path Traversal, SSRF |
| ציוד רפואי מחובר (IoMT) | מוניטורים, מדי-סוכר BLE, ביו-ריאקטורים, אפליקציות ניידות | RCE, סיסמאות hard-coded, דליפת PHI ב-BLE |

**חדש בגרסה זו (עדכון אוגוסט 2026):** שלישיית ה-`/loadIG` ב-HAPI FHIR (SSRF קריטי 9.3), חמשת ה-CVE של DCMTK, גל שני-שלישי של OpenEMR (Broken Access Control + XSS), Santesoft Sante PACS, שלושה מכשירי IoMT חדשים, וסעיף 8 חדש — **שטח תקיפה חשוד שטרם דווח**.

**הממצא המרכזי:** לראשונה מזה שלוש שנים, ניצול חולשות ידועות הפך לגורם השורש הטכני המוביל לאירועי כופר במגזר הבריאות — כ-33% מהתקיפות ב-2025. במקביל, 99% מבתי החולים בארה"ב מנהלים מכשירים המכילים חולשות ידועות ומנוצלות (KEV).

---

## 2. שרתי DICOM / PACS

### 2.1 Orthanc — סדרת חולשות 2026

תשע חולשות שסומנו **CVE-2026-5437 עד CVE-2026-5445**, המשפיעות על **כל הגרסאות עד 1.12.10 כולל**. השורש: אימות לקוי של מטא-דאטה, בדיקות חסרות, וחישובים אריתמטיים לא בטוחים.

הטבלה מציגה **מדגם מייצג** של 4 מתוך 9 (הבולטות ביותר); CVE-2026-5441 עד 5445 אינן מפורטות כאן — לפרטים המלאים ראו CERT/CC VU#536588 ואת הודעת Orthanc:

| CVE | סוג | השפעה |
|---|---|---|
| CVE-2026-5437 | Out-of-bounds read בפרסר של ה-meta-header | דליפת מידע / קריסה |
| CVE-2026-5438 | GZIP decompression bomb בטיפול בבקשות HTTP | מיצוי משאבים |
| CVE-2026-5439 | מיצוי זיכרון בעיבוד ארכיוני ZIP | DoS |
| CVE-2026-5440 | Heap-based buffer overflow בפרסינג/דקודינג תמונות | פוטנציאל ל-**RCE** |
| CVE-2026-5441 … 5445 | (מדגם — לא מפורט; ראו VU#536588) | קריסה / דליפה / DoS |

**תיקון:** שדרוג ל-**Orthanc 1.12.11**. ראו גם CERT/CC VU#536588.

### 2.2 Orthanc — חולשות קודמות שעדיין נפוצות בשטח

| CVE | CVSS | תיאור |
|---|---|---|
| CVE-2025-0896 | 9.8 | אימות בסיסי (basic auth) **אינו מופעל כברירת מחדל** כשגישה מרחוק מאופשרת, בכל הגרסאות לפני 1.5.8. תוקף מקבל גישה, שינוי רשומות ו-DoS בעצם ההתחברות. |
| CVE-2025-27578 | 8.7 | Use-after-free דרך העלאת קובץ DICOM זדוני → memory corruption / DoS |
| CVE-2023-33466 | 8.8 | דריסת קבצים שרירותית → RCE מאומת באמצעות קבצי **DICOM polyglot** |

**מיטיגציה מיידית ל-CVE-2025-0896** (אם אי אפשר לשדרג): הגדרת `"AuthenticationEnabled": true` בקובץ הקונפיגורציה.

### 2.2.1 Santesoft Sante PACS Server (ICSMA-25-224-01)

חמש חולשות **בכל הגרסאות לפני 4.2.3**, שלוש מהן ניתנות לניצול מרחוק בסיבוכיות נמוכה. **MS-ISAC סיווג "PATCH NOW".**

| CVE | תיאור |
|---|---|
| CVE-2025-54156 | **קריטית** — גניבת אישורים מרחוק |
| CVE-2025-53948 | טיפול בהודעות HL7: מספרי frame לא-רציפים → double free (memory corruption) |
| CVE-2025-54759 | **Stored XSS דרך הודעת HL7** — הזרקת payload לשדות HL7 שמורנדר ב-UI של השרת |
| CVE-2025-54862 | XSS בפורטל הווב → גניבת cookie סשן |

**תיקון:** שדרוג ל-4.2.3+. **נקודה מעניינת:** וקטור התקיפה הוא הודעת **HL7** עצמה — כלומר תוכן קליני לגיטימי לכאורה הופך לנשא של XSS. זהו דפוס "trust the clinical message" שחוזר גם ב-Mirth (סעיף 4.1).

### 2.3 חשיפה לאינטרנט — הבעיה שמתחת לחולשות

סריקות Shodan (נובמבר–דצמבר 2025) העלו תמונה חמורה:

- **3,627** שרתי DICOM חשופים לאינטרנט; זוהו 334 ארגונים, מתוכם **231 ארגוני בריאות** (בתי חולים, מרפאות, מעבדות ומכוני הדמיה).
- רק **0.14%** מהשרתים החשופים משתמשים ב-TLS.
- **99.56%** קיבלו חיבורים ללא אכיפת ולידציית **AE Title**.
- שרת DICOM ציבורי נסרק בין **4 ל-22 פעמים ביום**.
- ניתן לחלץ שמות מטופלים באמצעות `findscu` מול פורט 104 — ללא כל אימות.

**מסקנה תפעולית:** ברוב המקרים אין צורך בחולשה כלל. הקשחת חשיפה (segmentation, VPN, TLS, אכיפת AE Title) מספקת יותר ערך הגנתי מיידי מאשר טלאי בודד.

---

## 3. מערכות EMR / EHR

### 3.1 OpenEMR

מחקר אוטומטי (AI-assisted) איתר **38 CVE-ים חדשים בשלושה חודשים**, כולם דווחו לצוות OpenEMR ותוקנו.

| CVE | CVSS | תיאור |
|---|---|---|
| CVE-2026-24908 | **9.9** | SQL Injection ב-Patient REST API. משתמש מאומת עם גישת API מריץ שאילתות SQL שרירותיות → גישה מלאה ל-DB וחשיפת PHI. |
| CVE-2026-23627 | 8.8 | SQL Injection במודול מעקב חיסונים → exfiltration, גניבת אישורים, ואף הרצת קוד |
| CVE-2026-25746 | — | SQL Injection ברשימת המרשמים (prescription listing), ולידציית קלט חסרה, בגרסאות לפני 8.0.0 |

**גל שני — Broken Access Control (לפני 8.0.0):** ארבע חולשות שבהן משתמש בהרשאה נמוכה (למשל Receptionist) עוקף בקרת גישה. הדפוס החוזר: אימות סשן ו-CSRF token קיימים, אבל **בדיקת ACL חסרה לחלוטין**.

| CVE | תיאור |
|---|---|
| CVE-2026-25124 | ייצוא כל רשימת ההודעות (`message_list.php`) עם PHI של מטופלים ומשתמשים — ללא בדיקת הרשאה, רק CSRF |
| CVE-2026-25127 | Broken Access Control במודול Care Coordination — משתמש לא מורשה צופה במידע של משתמשים מורשים |
| CVE-2026-25131 | הוספה/שינוי של סוגי פרוצדורות (`types_edit.php`) ע"י משתמש בהרשאה נמוכה |
| CVE-2026-25135 | Broken Access Control נוסף (ראו ייעוץ) |

**גל שלישי (תוקן ב-8.0.0.3, מרץ 2026):**
- **CVE-2026-33912** — Stored XSS ב-`custom/ajax_download.php`; פרמטרי POST/GET מעובדים ללא סניטציה → הרצת JS בדפדפן הקורבן.
- **דליפת PHI ב-billing** — endpoint הורדת קבצי claim batch מוודא רק סשן ו-CSRF, ללא ACL → כל משתמש מאומת מוריד **ומוחק לצמיתות** קבצי תביעות עם PHI.

**תיקון:** שדרוג ל-**OpenEMR 8.0.0.3** ומעלה (8.0.0 סוגר את גלים 1–2; 8.0.0.3 סוגר את גל 3).
**תובנת שורש:** הדפוס `session + CSRF אבל ללא ACL` חוזר על עצמו לרוחב המוצר — זהו סימן לפער ארכיטקטוני שיטתי, לא באג נקודתי (בסיס לדפוס P3 בסעיף 8).
**דגש:** רוב החולשות דורשות אימות — כלומר גורם פנימי, חשבון גנוב או חשבון API של ספק צד-ג' הופך מיידית ל-DB compromise מלא. זהו טיעון חזק לעקרון ההרשאה המזערית על חשבונות API.

### 3.2 OpenMRS

**CVE-2026-41258 (קריטי) — Stored Velocity SSTI → RCE**

המתודה `ConceptReferenceRangeUtility.evaluateCriteria()` מריצה מחרוזות criteria השמורות ב-DB כתבניות Apache Velocity ללא sandbox. ה-`VelocityEngine` מאותחל עם `noSecureUberspector` בלבד, כלומר `UberspectImpl` ברירת המחדל נשאר — מה שמאפשר **reflection בלתי מוגבל של Java** דרך ביטויי תבנית.

- **וקטור:** משתמש עם הרשאת `Manage Concepts` שומר ביטוי Velocity זדוני בשדה reference range של concept. הקוד מורץ **אוטומטית** בכל פעם שמשתמש או קריאת API מבצעים ולידציה של observation מול אותו concept.
- **גרסאות מושפעות:** 2.7.0–2.7.8, 2.8.0–2.8.5
- **תוקן ב:** 2.7.9, 2.8.6 ומעלה

בנוסף, מבדקי חדירה על OpenMRS העלו broken access control ו-stored XSS שעלול לחשוף סיסמאות.

---

## 4. שכבת האינטגרציה — HL7 / FHIR

### 4.1 Mirth Connect (NextGen Healthcare) — CVE-2023-43208

**החולשה הכי משמעותית מבצעית ברשימה הזו.** RCE **לא-מאומת** בפלטפורמת האינטגרציה הנפוצה ביותר לעיבוד רשומות מטופלים (HL7, XML).

- **מנגנון:** Insecure deserialization ב-API. תוקף שולח payload XML מעוצב; האפליקציה אינה מוודאת את הנתונים לפני עיבודם, והקוד רץ בהרשאות שירות Mirth Connect.
- **גרסאות מושפעות:** כל הגרסאות לפני **4.4.1**
- **הקשר:** נובע מתיקון חלקי של CVE-2023-37679. **היה בניצול אקטיבי בטבע.**

Mirth יושב בדרך כלל במרכז הרשת הקלינית עם קישוריות לכל מערכת — EMR, LIS, PACS, מערכות חיוב. הרצת קוד עליו שקולה למעשה לדריסת כל זרימת הנתונים הקלינית.

### 4.2 HAPI FHIR — שלישיית ה-`/loadIG` (מרץ 2026) ⭐ החמור ביותר במשפחה

שלושה CVE-ים שפורסמו ב-**31 במרץ 2026** נגד המימוש הנפוץ ביותר של HL7 FHIR ב-Java. הבעיה המרכזית: שירות ה-**FHIR Validator HTTP** חושף endpoint בשם `/loadIG` שמקבל URL מגוף JSON ומבצע בקשה יוצאת אליו — **ללא אימות, ללא ולידציית hostname/scheme, ללא allowlist.**

| CVE | CVSS | תיאור |
|---|---|---|
| **CVE-2026-34361** | **9.3 (Critical)** | SSRF ב-`/loadIG` **בשרשור עם באג ב-`startsWith()`** בספק האישורים (`ManagedWebAccessUtils.getServer()`). תוקף רושם דומיין שמהווה prefix-match ל-URL של שרת FHIR מוגדר — והשרת שולח לו את **טוקני האימות** (Bearer, Basic, API keys) שהוגדרו עבור השרת הלגיטימי. גניבת אישורים מלאה, ללא אימות. |
| CVE-2026-34360 | — | Blind SSRF ב-`/loadIG`. תוקף לא-מאומת עם גישת רשת לוולידטור סורק שירותים פנימיים, **endpoint-ים של cloud metadata**, וממפה טופולוגיית רשת דרך דליפת מידע מבוססת-שגיאות. |
| CVE-2026-55471 | — | **XXE** ב-`XsltUtilities.saxonTransform()`. כל ה-overloads מייצרים `net.sf.saxon.TransformerFactoryImpl()` חשוף ללא הגבלת external-access, כך ש-XML עובר פרסינג עם ישויות חיצוניות ו-DTD חיצוני מאופשרים → קריאת קבצים מקומיים ו-blind XXE/SSRF. |

**תוקן בגרסה 6.9.4 של ארטיפקטי ה-Maven** `org.hl7.fhir.validation` / `org.hl7.fhir.core` / `org.hl7.fhir.utilities` — **לא בהכרח מספר גרסת אפליקציית HAPI FHIR**. יש לוודא את גרסת התלות (`org.hl7.fhir.*`) המותקנת בפועל, כי גרסת אפליקציה עשויה למשוך ארטיפקט validator ישן וחשוף.

### 4.3 HAPI FHIR — חולשות נוספות

| CVE | סוג | תיאור |
|---|---|---|
| CVE-2026-33180 | Information Disclosure | לפני גרסה 6.9.0: כאשר לקוח ה-HTTP הפנימי מוגדר לעקוב אחר redirects ומקבל 30X, הוא שולח את **כל הכותרות** — כולל אלה של הבקשה המקורית — ליעד שב-`Location`. טוקני אימות ומזהי סשן דולפים ליעד לא מהימן → התחזות לחשבון. |
| CVE-2026-45367 | ReDoS | מיצוי CPU ושיבוש שירות. **ללא צורך באימות** — די בשליחת FHIR resource או ביטוי FHIRPath עם regex בעל backtracking קטסטרופלי. משפיע על כל אפליקציה שחושפת את endpoint ה-FHIR Validator. |

> **דגש תפעולי:** שלוש מהחולשות לעיל (34360, 34361, 45367) מתנקזות ל-endpoint אחד — ה-FHIR Validator. אם אינכם זקוקים לו בפרודקשן, אל תחשפו אותו. זהו ה-single point of exposure המשמעותי ביותר בשכבת ה-FHIR.

---

## 5. ספריות DICOM וצפיינים — שרשרת האספקה של ההדמיה

זהו הרובד שהכי קל לפספס: הספריות האלה מוטמעות בתוך מוצרים מסחריים רבים, כך שהחשיפה שלכם עשויה להיות עקיפה.

| מוצר | CVE / התראה | סוג | פרטים |
|---|---|---|---|
| **pynetdicom** | CVE-2026-56445 (ICSMA-26-176-01) | Path Traversal, כתיבת קבצים לא-מאומתת | שרת ה-Q/R המובנה `qrscp` בונה את נתיב הכתיבה מתוך ה-`SOPInstanceUID` של הדאטהסט **ללא סניטציה**. תוקף לא-מאומת שולח C-STORE שה-UID בו בורח מתיקיית האחסון וכותב קובץ לנתיב שרירותי. **כל הגרסאות עד v3.0.4 — אין גרסת תיקון.** |
| **DCMTK** | **חמישייה** (ICSMA-26-181-01, 30/6/2026) | Path Traversal / דליפה / DoS | חמש חולשות שגילה Abhinav Agarwal, **בכל הגרסאות לפני v3.7.0**: **CVE-2026-50003** (Critical, CVSS 9.8) — path traversal בלקוח bit-preserving C-GET, כתיבה מחוץ לתיקיית היעד עם `../` ונתיבים אבסולוטיים; **CVE-2026-52868** — גישה לא מורשית לרשומות worklist; **CVE-2026-50254** — memory leak → שיבוש שירות; **CVE-2026-35505** ו-**CVE-2026-44628** (High, 7.5–8.2). תוקן בקומיטים האחרונים. |
| **OHIF Viewer** | CVE-2026-12473 (ICSMA-26-176-02) | SSRF, CVSS 8.2/8.3 | מקורות הנתונים `DICOMWebProxy` ו-`DICOMJSON` שבקונפיגורציית ברירת המחדל מושכים URL מפרמטר ללא ולידציה, ושירות האימות הגלובלי מזריק אוטומטית את **טוקן ה-OIDC Bearer של הרופא** לבקשה — ושולח אותו לשרת התוקף. מקורות DICOMweb אינם מושפעים. **תוקן ב-v3.12.2.** |
| **GDCM** | CVE-2026-3650 (ICSMA-26-083-01), CVE-2025-11266 | Out-of-bounds write / DoS | פרסינג של קובץ DICOM פגום עם פרגמנטי PixelData מקופסלים → underflow של מספר שלם לא-מסומן באינדוקס באפר → segfault. די ב**פתיחת קובץ זדוני**. הקצאות זיכרון עצומות ממלאות את ה-heap בקריאה אחת. גרסה 3.2.2 מושפעת; **המתחזק לא נענה לפניות CISA.** |
| **MicroDicom** | CVE-2025-5943 | RCE | ניצול מרחוק בסיבוכיות נמוכה → הרצת קוד שרירותי. גרסה 2025.2 (Build 8154) ומטה. |
| **MicroDicom** | CVE-2025-35975, CVE-2025-36521 | Out-of-bounds | ראו ICSMA-25-121-01 |
| **MicroDicom** | CVE-2025-1002 | עדכון לא מאובטח, CVSS 5.7 | אי-אימות תעודת שרת העדכונים. גרסה 2024.03; תוקן ב-2025.1. |
| **RadiAnt** | CVE-2025-1001 | MITM, CVSS 5.7 | מנגנון העדכון אינו מאמת את תעודת שרת העדכונים → הגשת עדכון זדוני. גרסה 2024.02. |

**התבנית החוזרת:** שני אנטי-פטרנים חוזרים על עצמם כאן —
1. **אמון בתוכן קובץ ה-DICOM** כמקור לנתיבי מערכת קבצים (pynetdicom, DCMTK, CVE-2023-33466).
2. **ערוצי עדכון ללא אימות תעודה** (MicroDicom, RadiAnt) — וקטור אספקה קלאסי.

---

## 6. ציוד רפואי מחובר (IoMT)

| מכשיר | התראה | ממצא |
|---|---|---|
| Contec Health CMS8000 (מוניטור מטופל) | ICSMA-25-030-01 | **שתי התנהגויות נפרדות:** (1) תוקף שולח בקשות **UDP** מעוצבות → כתיבת נתונים שרירותית ו-RCE; (2) **המכשיר עצמו יוזם חיבור יוצא** לכתובת חיצונית **מקודדת-קשיח** ומדליף אליה מידע מטופלים ונתוני חיישנים (backdoor). **מיטיגציה נפרדת לכל אחת:** חסימת/ניטור ה-UDP הנכנס, **וגם** חסימת/ניטור התעבורה ה**יוצאת** לכתובת הקשיחה. |
| Medtronic MyCareLink | ICSMA-25-205-01 | סיכון נמוך — דורש חבלה פיזית. עדכוני אבטחה מיוני 2025. |
| Fourth Frontier Frontier X / X2 | ICSMA-26-148-01 | אפליקציה ניידת + מכשיר לבישה |
| Apollo Pharmacy APG-01 BT (מד סוכר) | ICSMA-26-169-01 | **CVE-2026-50034 + CVE-2026-52866** — BLE: אימות לקוי מאפשר pairing ללא אישור משתמש, ושידור **לא מוצפן** של ערכי סוכר והגדרות. תוקף בטווח BLE מיירט מידע בריאותי ב-plaintext. Apollo לא נענתה ל-CISA. |
| Eppendorf BioFlo 320 (ביו-ריאקטור) | ICSMA-26-146-01 | **CVE-2026-7251** — שרת VNC עם **סיסמה מקודדת-קשיח (hard-coded)**. תוקף שיודע את כתובת הרשת משתלט על מלוא ממשק הבקרה. VNC לא מוצפן. תוקן ע"י הסרת VNC. |
| ZOLL ePCR (אפליקציית iOS) | ICSMA-26-041-01 | **CVE-2025-12699** — קלט לא-מסונן משתקף ל-WebView; מחרוזות בשדות PCR מתפרשות כ-HTML/JS → קריאת קבצים מקומיים ו-PHI. האפליקציה הוצאה משירות (מאי 2025) — אך ממחישה סיכון legacy. |

**האתגר המבני:** מערכות קליניות legacy לא ניתנות לטלאי מבלי להוציא ציוד משירות. לכן ההגנה חייבת להיות **מפצה** (compensating): סגמנטציה, בקרת גישה לרשת, וניטור.

---

## 7. הקשר רחב — כיצד תוקפים נכנסים בפועל

- **33%** מאירועי הכופר בבריאות ב-2025 החלו מניצול חולשה ידועה (גורם השורש המוביל, לראשונה מזה 3 שנים).
- **32%** מתקיפות הכופר בארה"ב החלו מ**התקני VPN ו-edge לא מעודכנים**.
- **23%** מהתקיפות השתמשו באישורים גנובים (infostealers / פישינג).
- **82%** מהדליפות מקורן בגניבת אישורים דרך דוא"ל או SMS.
- **וקטור שרשרת האספקה מס' 1:** ספקי חיוב, מעבדה ורדיולוגיה עם גישה מורשית לרשת ו-MFA לקוי, וספקי צד-ג' עם הרשאות אדמין קבועות ללא אכיפת MFA.
- ברבעון הראשון של 2026 נרשמו **120** תקיפות כופר על ארגוני בריאות.

**התובנה:** ה-CVE-ים בטבלאות שלמעלה חשובים, אבל הרוב המכריע של האירועים מתחיל בהיקף הרשת (edge/VPN), באישורים גנובים ובגישת ספקים — לא בחולשת zero-day במערכת הקלינית עצמה.

---

## 8. שטח תקיפה חשוד — חולשות שטרם דווחו (Threat-Hunting Leads)

> ⚠️ **הבהרה:** סעיף זה אינו מדווח על חולשות קיימות ואינו כולל קוד ניצול. אלו **השערות הגנתיות** (hunting hypotheses) המבוססות על הכללה של הדפוסים המאומתים מהסעיפים לעיל — היכן סביר שיתגלו CVE-ים נוספים. השימוש המיועד: תעדוף בדיקות מורשות, code review, ו-fuzzing על מערכות **שבבעלותכם**. יש לדווח כל ממצא באחריות (responsible disclosure) למתחזק.

### 8.1 מדוע אפשר לחזות היכן — חמישה דפוסי-שורש חוזרים

מהצלבת כל ה-CVE-ים לעיל עולים חמישה אנטי-פטרנים שכל אחד מהם הופיע ב-3+ מוצרים שונים. מוצר שמפגין אחד מהם באזור אחד — סביר שמפגין אותו גם במקומות שטרם נבדקו:

| # | דפוס-שורש | הופיע ב | הכללה: היכן לחפש עוד |
|---|---|---|---|
| P1 | **אמון בתוכן קובץ DICOM כמקור לנתיב FS** | pynetdicom (SOPInstanceUID), DCMTK (C-GET), CVE-2023-33466 | כל שדה DICOM שנגזר ממנו שם קובץ/תיקייה: `SeriesInstanceUID`, `PatientID`, `Modality`, שמות בתוך ארכיוני ZIP |
| P2 | **פרסרים של פורמטים בינאריים ב-C/C++** ללא bounds-checking | Orthanc, GDCM, DCMTK, MicroDicom | פרסרים של פורמטים "אקזוטיים": RT-STRUCT, encapsulated PDF, waveform, מקודדי JPEG2000/JPEG-LS מוטמעים |
| P3 | **`session + CSRF אבל ללא ACL`** | OpenEMR (25124/25127/25131, billing) | כל endpoint של ייצוא/דוח/הורדה בקבצי PHP/REST שלא נבדק — במיוחד bulk export ו-report generation |
| P4 | **"trust the clinical message"** — HL7/FHIR כנשא הזרקה | Mirth (deserialization), Sante (HL7→XSS), FHIR (loadIG) | פרסינג של הודעות HL7v2 (segments MSH/PID/OBX), רינדור שדות FHIR ב-UI, טרנספורמציות XSLT/Velocity/FHIRPath |
| P5 | **ערוצי עדכון / שירותי ניהול ללא אימות** | MicroDicom, RadiAnt (עדכון), Eppendorf (VNC hard-coded), Orthanc (auth כבוי) | ממשקי ניהול פתוחים כברירת מחדל, סיסמאות ברירת-מחדל/מקודדות, DICOMweb/ממשקי REST ללא TLS |

### 8.2 יעדי בדיקה בעדיפות גבוהה (hunting priorities)

- **P1 — הרחבת ה-path traversal ל-`STORESCP` ו-web-upload.** ה-CVE של pynetdicom (CVE-2026-56445) התמקד ב-`qrscp`. אותו דפוס של בניית נתיב מ-UID לא-מסונן צפוי בשרתי C-STORE אחרים ובנתיבי העלאת DICOM דרך HTTP. **בדיקה:** dataset עם UID המכיל `../` או null-byte, מול כל נתיב קליטה של המוצר, בסביבת בדיקה מבודדת.
- **P2 — fuzzing ממוקד על מקודדי-תמונה מוטמעים.** GDCM ו-DCMTK תוקנו רק על נתיבים ספציפיים; ספריות כמו CharLS (JPEG-LS) ו-OpenJPEG (JPEG2000) המוטמעות בתוכן נגזרות מאותה משפחת חולשות memory-corruption. **בדיקה:** AFL++/libFuzzer על ה-decoders, עם קורפוס DICOM חוקי כזרע.
- **P3 — audit שיטתי של ACL ב-OpenEMR ו-fork-ים שלו.** בהינתן שהדפוס התגלה ב-4+ endpoint-ים נפרדים, סביר שנותרו עוד. **בדיקה:** מיפוי כל endpoint שנוגע ב-PHI מול מטריצת ההרשאות, וזיהוי כאלה שבודקים רק `verifyCsrfToken()` ללא `AclMain::aclCheckCore()`.
- **P4 — Mirth channels מותאמים-אישית.** ה-RCE הליבתי תוקן, אך טרנספורמרים מבוססי-JavaScript/Velocity בערוצים שנכתבו בארגון הם שטח תקיפה חדש לגמרי בכל התקנה. **בדיקה:** סקירת קוד של transformer/filter scripts עבור `eval`, deserialization, ו-command execution על תוכן הודעה נכנס.
- **P4 — FHIRPath/Velocity/XSLT כמנועי-תבנית.** דפוס ה-SSTI של OpenMRS (Velocity) וה-XXE של HAPI (Saxon) מרמזים ששאר מנועי הביטויים בסטאק ה-FHIR לא נבדקו באותה קפדנות. **בדיקה:** כל מקום שבו ביטוי שמקורו במשתמש/DB מגיע ל-engine — במיוחד `$fhirpath`, custom SearchParameters, ו-StructureMap.
- **P5 — מיפוי חשיפה חיצוני.** לא "חולשה" אלא ודאות סטטיסטית: בהינתן ש-99.56% מהשרתים החשופים אינם אוכפים AE Title, כל שרת שלכם החשוף לאינטרנט הוא ממצא בהמתנה. **בדיקה:** סריקת ההיקף החיצוני שלכם (פורטים 104, 11112, 4242, 8042, 8080) מנקודת מבט חיצונית.

### 8.3 מוצרים ב"סיכון מוגבר" ללא מתחזק פעיל

יש להבחין בין **מתחזק שאינו מגיב** לבין **חולשה שטרם תוקנה**:
- **GDCM** — המתחזק **לא נענה** לפניות CISA (סעיף 5). כאן ההנחה "חולשות נוספות יתגלו ולא יתוקנו" מוצדקת; סיכון שיורי קבוע.
- **pynetdicom (`qrscp`)** — **אין גרסת תיקון** ל-CVE-2026-56445 (נכון לכתיבה), אך זו קביעה על **זמינות טלאי בלבד** — CISA לא דיווחה על מתחזק לא-מגיב. אין להסיק מכך שהפרויקט נטוש; ייתכן שתיקון יגיע.

בשני המקרים, עד שיש טלאי, חובה sandbox ובקרות מפצות (סעיף 9) — אך רק ל-GDCM מוצדקת ההנחה שהתחזוקה עצמה כשלה.

---

## 9. רשימת פעולות מומלצת (Hardening Checklist)

### תעדוף מיידי — עדכונים
- [ ] **Mirth Connect** → 4.4.1+ (RCE לא-מאומת, בניצול אקטיבי) — הגבוה ביותר בעדיפות
- [ ] **OpenEMR** → **8.0.0.3+** (8.0.0–8.0.0.2 עדיין חשופות לגל השלישי — XSS ומחיקת קבצי claim עם PHI)
- [ ] **OpenMRS** → 2.7.9 / 2.8.6+
- [ ] **Orthanc** → 1.12.11
- [ ] **Santesoft Sante PACS** → **4.2.3+** (חמש חולשות, MS-ISAC "PATCH NOW")
- [ ] **DCMTK** → **3.7.0+** (path traversal קריטי CVSS 9.8, CVE-2026-50003)
- [ ] **OHIF** → 3.12.2+ (וניקוי קונפיגורציות `DicomWebProxyDataSource` / `DicomJSONDataSource` שאינן בשימוש)
- [ ] **HAPI FHIR** → שדרוג הארטיפקטים `org.hl7.fhir.validation/core/utilities` ל-**6.9.4+** (זו הגרסה של ארטיפקטי ה-Validator ב-Maven שמתקנת את loadIG/XXE — לא בהכרח מספר גרסת אפליקציית HAPI FHIR; ודאו את גרסת התלות המותקנת), ובדיקת חשיפת endpoint ה-Validator
- [ ] **MicroDicom** → גרסה **חדשה מ-2025.2 build 8154** (זו והקודמות פגיעות ל-RCE, CVE-2025-5943); אם אין — בקרות מפצות
- [ ] **pynetdicom / GDCM** → אין תיקון זמין. יש להחיל בקרות מפצות (ראו למטה).

### בקרות מפצות במקום שאין טלאי
- [ ] אין להריץ `qrscp` של pynetdicom בפרודקשן חשוף. אם חובה — הרצה בקונטיינר עם FS לקריאה בלבד מחוץ לתיקיית האחסון, ומשתמש לא מורשה.
- [ ] פרסינג של קבצי DICOM שמקורם חיצוני יבוצע ב-sandbox מבודד (קונטיינר חד-פעמי, ללא רשת, מכסות זיכרון).
- [ ] הגבלת גודל וקצב על העלאות DICOM/ZIP (נגד decompression bombs).

### הקשחת רשת ותצורה
- [ ] אף שרת DICOM/PACS אינו חשוף ישירות לאינטרנט. אימות מול Shodan/Censys מנקודת מבט חיצונית.
- [ ] אכיפת **AE Title** כ-**defense-in-depth בלבד** — ה-AE Title הוא מזהה שנשלט ע"י השולח וניתן לזייף/להעתיק, ולכן **אינו אימות עמית**. גבול אמיתי מחייב **DICOM-TLS עם אימות הדדי**, VPN, או בקרת גישה ברמת הרשת.
- [ ] TLS על תעבורת DICOM (`DICOM-TLS`, רצוי mutual-TLS), ולא רק בשכבת ה-HTTP.
- [ ] סגמנטציית רשת בין הרשת הקלינית, רשת המכשור (IoMT) ורשת ה-IT הארגונית.
- [ ] **MFA לכל גישת ספק צד-ג'**, וביטול הרשאות אדמין קבועות לטובת גישה מוגבלת בזמן.
- [ ] הרשאה מזערית לחשבונות API (במיוחד מול OpenEMR REST API — שם הפער בין "מאומת" ל"DB מלא" הוא CVSS 9.9).

### ניטור וזיהוי
- [ ] התראה על תעבורת DICOM יוצאת ליעדים לא מוכרים (וקטור ה-C-GET של DCMTK).
- [ ] **עבור OHIF במיוחד:** ניטור והגבלת **egress של HTTP(S)/DNS** מ-backend ה-viewer/proxy — ה-SSRF של OHIF (DICOMWebProxy/DICOMJSON) מושך URL תוקף ב-HTTP ודולף טוקן OIDC; ניטור תעבורת DICOM בלבד **לא** יזהה אותו.
- [ ] ניטור קריסות של תהליכי PACS — memory corruption מתחיל לרוב כ-DoS לפני שהופך ל-RCE יציב.
- [ ] מעקב אחר **CISA ICS Medical Advisories (ICSMA)** כערוץ קבוע.
- [ ] הצלבת מלאי המכשירים מול קטלוג ה-**KEV** של CISA.

---

## 10. מקורות

**DICOM / PACS**
- [Santesoft Sante PACS Server — HIPAA Journal](https://www.hipaajournal.com/remotely-exploitable-vulnerabilities-santesoft-sante-pacs-server/) · [ICSMA-25-224-01, CISA](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-25-224-01) · [MS-ISAC PATCH NOW advisory](https://www.cisecurity.org/advisory/ms-isac-cybersecurity-advisory---multiple-vulnerabilities-in-sante-pacs-server-could-allow-for-remote-code-execution---patch-now---tlp-clear_2025-026)
- [OFFIS DCMTK — quintet of bugs, HIPAA Journal](https://www.hipaajournal.com/offis-dcmtk-vulnerabilities-june-2026/) · [ICSMA-26-181-01, CISA](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-26-181-01) · [CVE-2026-52868 — CVE.org](https://www.cve.org/CVERecord?id=CVE-2026-52868)
- [Grassroots DICOM DoS (CVE-2026-3650) — SentinelOne](https://www.sentinelone.com/vulnerability-database/cve-2026-3650/) · [CISA Flags Critical Flaw in GDCM — HealthcareInfoSecurity](https://www.healthcareinfosecurity.com/cisa-flags-critical-flaw-in-grassroots-dicom-imaging-library-a-31246)
- [Orthanc DICOM Vulnerabilities Lead to Crashes, RCE — SecurityWeek](https://www.securityweek.com/orthanc-dicom-vulnerabilities-lead-to-crashes-rce/)
- [VU#536588 — Multiple Heap Buffer Overflows in Orthanc DICOM Server, CERT/CC](https://www.kb.cert.org/vuls/id/536588)
- [CVE-2025-0896 (CVSS 9.8): Orthanc DICOM Server Flaw — securityonline.info](https://securityonline.info/cve-2025-0896-cvss-9-8-orthanc-dicom-server-flaw-exposes-medical-images-to-unauthorized-access/)
- [Vulnerabilities Identified in Orthanc Server and MicroDicom DICOM Viewer — HIPAA Journal](https://www.hipaajournal.com/vulnerabilities-orthanc-server-microdicom-dicom-viewer/)
- [CVE-2023-33466 — Exploiting Healthcare Servers with Polyglot Files, Shielder](https://www.shielder.com/blog/2023/10/cve-2023-33466-exploiting-healthcare-servers-with-polyglot-files/)
- [Uncovering New Vulnerabilities in PACS Servers and DICOM Viewers — TXOne Networks](https://www.txone.com/blog/uncovering-new-vulnerabilities-in-pacs-servers-and-dicom-viewers/)
- [Penetration Testing of the DICOM Protocol — IOActive](https://www.ioactive.com/penetration-testing-of-the-dicom-protocol-real-world-attacks/)

**חשיפה לאינטרנט**
- [Exposed DICOM Servers in UK Healthcare — Rapid7](https://www.rapid7.com/blog/post/tr-mri-hidden-risks-exposed-dicom-servers-uk-healthcare/)
- [A Hidden Vulnerability in Healthcare: Exposed DICOM Servers — Trend Micro](https://www.trendmicro.com/vinfo/us/security/news/cybercrime-and-digital-threats/a-hidden-vulnerability-in-healthcare-exposed-dicom-servers-and-the-risk-to-patient-data)
- [Healthcare Organizations Exposing Patient Data Via Poorly Secured DICOM Servers — HIPAA Journal](https://www.hipaajournal.com/healthcare-organizations-exposing-patient-data-dicom-servers/)
- [Measuring Healthcare Data Leaks and Security Flaws at Internet Scale — arXiv](https://arxiv.org/html/2607.04965v1)

**EMR / EHR**
- [AI Finds 38 Security Flaws in OpenEMR — Dark Reading](https://www.darkreading.com/vulnerabilities-threats/ai-finds-38-security-flaws-openemr)
- [38 Vulnerabilities Found in OpenEMR Medical Software — SecurityWeek](https://www.securityweek.com/38-vulnerabilities-found-in-openemr-medical-software/)
- [CVE-2026-25746: OpenEMR SQL Injection — SentinelOne](https://www.sentinelone.com/vulnerability-database/cve-2026-25746/)
- [OpenMRS Stored Velocity SSTI to RCE — CVE-2026-41258, GitHub Advisory](https://github.com/advisories/GHSA-xj4f-8jjg-vx4q)
- [OpenEMR Broken Access Control (25124/25127/25131/25135) — cyberleveling](https://cyberleveling.com/blog/openemr-vulnerabilities) · [CVE-2026-25127 — cvefeed](https://cvefeed.io/vuln/detail/CVE-2026-25127)
- [OpenEMR XSS CVE-2026-33912 — SentinelOne](https://www.sentinelone.com/vulnerability-database/cve-2026-33912/)

**HL7 / FHIR / אינטגרציה**
- [CVE-2023-43208 (Mirth Connect RCE): Analysis & Detection — Huntress](https://www.huntress.com/threat-library/vulnerabilities/cve-2023-43208)
- [Critical NextGen Healthcare Mirth Connect Vulnerability Under Active Exploitation — HIPAA Journal](https://www.hipaajournal.com/critical-nextgen-healthcare-mirth-connect-under-active-exploitation/)
- [HAPI FHIR SSRF+credential leak, CVE-2026-34361 — GitLab Advisories](https://advisories.gitlab.com/pkg/maven/ca.uhn.hapi.fhir/org.hl7.fhir.validation/CVE-2026-34361/) · [CVE-2026-34360 Blind SSRF via /loadIG](https://advisories.gitlab.com/pkg/maven/ca.uhn.hapi.fhir/org.hl7.fhir.core/CVE-2026-34360/) · [CVE-2026-55471 XXE saxonTransform](https://advisories.gitlab.com/pkg/maven/ca.uhn.hapi.fhir/org.hl7.fhir.utilities/CVE-2026-55471/)
- [HAPI FHIR Unauthenticated SSRF Leads to Auth Token Theft — TheHackerWire](https://www.thehackerwire.com/hapi-fhir-unauthenticated-ssrf-leads-to-auth-token-theft/)
- [SSRF Attacks on EHR Integration APIs — Prophaze](https://www.prophaze.com/ssrf-attacks-ehr-integration-apis-blind-spot-in-healthcare/)
- [CVE-2026-33180: HAPI FHIR Information Disclosure — SentinelOne](https://www.sentinelone.com/vulnerability-database/cve-2026-33180/)
- [HAPI FHIR ReDoS, CVE-2026-45367 — DailyCVE](https://dailycve.com/hapi-fhir-redos-cve-2026-45367-high/)

**התראות CISA ICS Medical**
- [ICSMA-26-176-01 — pydicom / pynetdicom Library](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-26-176-01)
- [ICSMA-26-176-02 — OHIF Viewers DICOM](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-26-176-02)
- [ICSMA-26-181-01 — OFFIS DCMTK Toolkit](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-26-181-01)
- [ICSMA-26-083-01 — Grassroots DICOM (GDCM)](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-26-083-01)
- [ICSMA-25-121-01 — MicroDicom DICOM Viewer](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-25-121-01)
- [ICSMA-25-051-01 — Medixant RadiAnt DICOM Viewer](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-25-051-01)
- [ICSMA-25-030-01 — Contec Health CMS8000 Patient Monitor](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-25-030-01)
- [ICSMA-25-205-01 — Medtronic MyCareLink Patient Monitor](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-25-205-01)
- [ICSMA-26-169-01 — Apollo Pharmacy APG-01 BT Blood Glucose Monitor](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-26-169-01)
- [ICSMA-26-146-01 — Eppendorf BioFlo 320 (hard-coded VNC)](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-26-146-01)
- [ICSMA-26-041-01 — ZOLL ePCR iOS Application](https://www.cisa.gov/news-events/ics-medical-advisories/icsma-26-041-01)
- [Study: 162 New Medical Device Vulnerabilities Found — Censinet](https://censinet.com/perspectives/study-162-new-medical-device-vulnerabilities-found)
- [CVE-2026-56445: Unauthenticated Arbitrary File Write in pynetdicom](https://www.machinespirits.com/advisory/1f9f99/)
- [CVE-2026-50003: DCMTK Path Traversal — SentinelOne](https://www.sentinelone.com/vulnerability-database/cve-2026-50003/)
- [High-Severity Vulnerability Identified in OHIF Viewers DICOM — HIPAA Journal](https://www.hipaajournal.com/high-severity-vulnerability-identified-in-ohif-viewers-dicom/)

**סטטיסטיקה ומגמות**
- [Healthcare Cybersecurity Statistics 2026 — ORDR](https://ordr.net/blog/healthcare-cybersecurity-statistics-2026-report)
- [Healthcare Cybersecurity 2026: Threats and How to Stop Them — CybelAngel](https://cybelangel.com/blog/healthcare-industry-guide-cyber/)
- [Ransomware in Healthcare 2026: The Attack Timeline — CybelAngel](https://cybelangel.com/blog/ransomware-in-healthcare-attack-timeline/)
- [Threats and Security Strategies for IoMT Infusion Pumps — arXiv](https://arxiv.org/pdf/2509.14604)
