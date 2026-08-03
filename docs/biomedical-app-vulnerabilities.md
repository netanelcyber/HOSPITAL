# פרצות אבטחה באפליקציות נפוצות בתחום הביו-רפואי

**עודכן:** אוגוסט 2026
**מטרה:** מסמך ייחוס הגנתי (defensive) — מיפוי חולשות ידועות ומפורסמות במערכות תוכנה נפוצות בסביבה הרפואית, לצורך הערכת סיכונים, תעדוף עדכונים והקשחה. כל המידע כאן מבוסס על CVE-ים פומביים, התראות CISA ומחקרים שפורסמו.

> ⚠️ המסמך אינו כולל קוד ניצול (exploit). השימוש המיועד הוא בדיקות מורשות בלבד, ניהול פגיעויות, והגנה על מערכות שבבעלותכם.

---

## 1. תקציר מנהלים

שטח התקיפה של סביבה רפואית מתחלק לחמישה רבדים, ובכולם התגלו ב-2025–2026 חולשות קריטיות:

| רובד | דוגמאות מוצרים | סיכון עיקרי |
|---|---|---|
| PACS / שרתי DICOM | Orthanc, dcm4chee | RCE, גישה לא-מאומתת לתמונות רפואיות |
| EMR / EHR | OpenEMR, OpenMRS | SQL Injection, SSTI→RCE, דליפת PHI |
| אינטגרציה (Interoperability) | Mirth Connect, HAPI FHIR | RCE לא-מאומת, דליפת טוקנים, DoS |
| ספריות וצפיינים לתמונות | GDCM, DCMTK, pydicom/pynetdicom, MicroDicom, RadiAnt, OHIF | Memory corruption, Path Traversal, SSRF |
| ציוד רפואי מחובר (IoMT) | מוניטורים, משאבות עירוי | RCE, תקשורת יוצאת לא מתועדת |

**הממצא המרכזי:** לראשונה מזה שלוש שנים, ניצול חולשות ידועות הפך לגורם השורש הטכני המוביל לאירועי כופר במגזר הבריאות — כ-33% מהתקיפות ב-2025. במקביל, 99% מבתי החולים בארה"ב מנהלים מכשירים המכילים חולשות ידועות ומנוצלות (KEV).

---

## 2. שרתי DICOM / PACS

### 2.1 Orthanc — סדרת חולשות 2026

תשע חולשות שסומנו **CVE-2026-5437 עד CVE-2026-5445**, המשפיעות על **כל הגרסאות עד 1.12.10 כולל**. השורש: אימות לקוי של מטא-דאטה, בדיקות חסרות, וחישובים אריתמטיים לא בטוחים.

| CVE | סוג | השפעה |
|---|---|---|
| CVE-2026-5437 | Out-of-bounds read בפרסר של ה-meta-header | דליפת מידע / קריסה |
| CVE-2026-5438 | GZIP decompression bomb בטיפול בבקשות HTTP | מיצוי משאבים |
| CVE-2026-5439 | מיצוי זיכרון בעיבוד ארכיוני ZIP | DoS |
| CVE-2026-5440 | Heap-based buffer overflow בפרסינג/דקודינג תמונות | פוטנציאל ל-**RCE** |

**תיקון:** שדרוג ל-**Orthanc 1.12.11**. ראו גם CERT/CC VU#536588.

### 2.2 Orthanc — חולשות קודמות שעדיין נפוצות בשטח

| CVE | CVSS | תיאור |
|---|---|---|
| CVE-2025-0896 | 9.8 | אימות בסיסי (basic auth) **אינו מופעל כברירת מחדל** כשגישה מרחוק מאופשרת, בכל הגרסאות לפני 1.5.8. תוקף מקבל גישה, שינוי רשומות ו-DoS בעצם ההתחברות. |
| CVE-2025-27578 | 8.7 | Use-after-free דרך העלאת קובץ DICOM זדוני → memory corruption / DoS |
| CVE-2023-33466 | 8.8 | דריסת קבצים שרירותית → RCE מאומת באמצעות קבצי **DICOM polyglot** |

**מיטיגציה מיידית ל-CVE-2025-0896** (אם אי אפשר לשדרג): הגדרת `"AuthenticationEnabled": true` בקובץ הקונפיגורציה.

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

**תיקון:** שדרוג ל-**OpenEMR 8.0.0** ומעלה.
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

### 4.2 HAPI FHIR

| CVE | סוג | תיאור |
|---|---|---|
| CVE-2026-33180 | Information Disclosure | לפני גרסה 6.9.0: כאשר לקוח ה-HTTP הפנימי מוגדר לעקוב אחר redirects ומקבל 30X, הוא שולח את **כל הכותרות** — כולל אלה של הבקשה המקורית — ליעד שב-`Location`. טוקני אימות ומזהי סשן דולפים ליעד לא מהימן → התחזות לחשבון. |
| CVE-2026-45367 | ReDoS | מיצוי CPU ושיבוש שירות. **ללא צורך באימות** — די בשליחת FHIR resource או ביטוי FHIRPath עם regex בעל backtracking קטסטרופלי. משפיע על כל אפליקציה שחושפת את endpoint ה-FHIR Validator. |

---

## 5. ספריות DICOM וצפיינים — שרשרת האספקה של ההדמיה

זהו הרובד שהכי קל לפספס: הספריות האלה מוטמעות בתוך מוצרים מסחריים רבים, כך שהחשיפה שלכם עשויה להיות עקיפה.

| מוצר | CVE / התראה | סוג | פרטים |
|---|---|---|---|
| **pynetdicom** | CVE-2026-56445 (ICSMA-26-176-01) | Path Traversal, כתיבת קבצים לא-מאומתת | שרת ה-Q/R המובנה `qrscp` בונה את נתיב הכתיבה מתוך ה-`SOPInstanceUID` של הדאטהסט **ללא סניטציה**. תוקף לא-מאומת שולח C-STORE שה-UID בו בורח מתיקיית האחסון וכותב קובץ לנתיב שרירותי. **כל הגרסאות עד v3.0.4 — אין גרסת תיקון.** |
| **DCMTK** | CVE-2026-50003 (ICSMA-26-181-01) | Path Traversal | שרת DICOM זדוני/נפרץ מאלץ לקוח DCMTK במצב bit-preserving C-GET לכתוב קבצים מחוץ לתיקיית היעד. מקבל גם `../` וגם נתיבים אבסולוטיים. |
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
| Contec Health CMS8000 (מוניטור מטופל) | ICSMA-25-030-01 | תוקף שולח בקשות UDP מעוצבות או מתחבר ל**רשת חיצונית לא מזוהה** ← כתיבת נתונים שרירותית ו-RCE. המכשיר גם מדליף מידע מטופלים ונתוני חיישנים לאותה רשת חיצונית. |
| Medtronic MyCareLink | ICSMA-25-205-01 | סיכון נמוך — דורש חבלה פיזית. עדכוני אבטחה מיוני 2025. |
| Fourth Frontier Frontier X / X2 | ICSMA-26-148-01 | אפליקציה ניידת + מכשיר לבישה |

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

## 8. רשימת פעולות מומלצת (Hardening Checklist)

### תעדוף מיידי — עדכונים
- [ ] **Mirth Connect** → 4.4.1+ (RCE לא-מאומת, בניצול אקטיבי) — הגבוה ביותר בעדיפות
- [ ] **OpenEMR** → 8.0.0+
- [ ] **OpenMRS** → 2.7.9 / 2.8.6+
- [ ] **Orthanc** → 1.12.11
- [ ] **OHIF** → 3.12.2+ (וניקוי קונפיגורציות `DicomWebProxyDataSource` / `DicomJSONDataSource` שאינן בשימוש)
- [ ] **HAPI FHIR** → 6.9.0+ ומעלה, ובדיקת חשיפת endpoint ה-Validator
- [ ] **MicroDicom** → 2025.1+ / הגרסה האחרונה
- [ ] **pynetdicom / GDCM** → אין תיקון זמין. יש להחיל בקרות מפצות (ראו למטה).

### בקרות מפצות במקום שאין טלאי
- [ ] אין להריץ `qrscp` של pynetdicom בפרודקשן חשוף. אם חובה — הרצה בקונטיינר עם FS לקריאה בלבד מחוץ לתיקיית האחסון, ומשתמש לא מורשה.
- [ ] פרסינג של קבצי DICOM שמקורם חיצוני יבוצע ב-sandbox מבודד (קונטיינר חד-פעמי, ללא רשת, מכסות זיכרון).
- [ ] הגבלת גודל וקצב על העלאות DICOM/ZIP (נגד decompression bombs).

### הקשחת רשת ותצורה
- [ ] אף שרת DICOM/PACS אינו חשוף ישירות לאינטרנט. אימות מול Shodan/Censys מנקודת מבט חיצונית.
- [ ] אכיפת **AE Title** בפועל — לא הגדרה בלבד, אלא בדיקה אקטיבית שחיבור עם AE Title לא מוכר נדחה.
- [ ] TLS על תעבורת DICOM (`DICOM-TLS`), ולא רק בשכבת ה-HTTP.
- [ ] סגמנטציית רשת בין הרשת הקלינית, רשת המכשור (IoMT) ורשת ה-IT הארגונית.
- [ ] **MFA לכל גישת ספק צד-ג'**, וביטול הרשאות אדמין קבועות לטובת גישה מוגבלת בזמן.
- [ ] הרשאה מזערית לחשבונות API (במיוחד מול OpenEMR REST API — שם הפער בין "מאומת" ל"DB מלא" הוא CVSS 9.9).

### ניטור וזיהוי
- [ ] התראה על תעבורת DICOM יוצאת ליעדים לא מוכרים (וקטור ה-SSRF של OHIF וה-C-GET של DCMTK).
- [ ] ניטור קריסות של תהליכי PACS — memory corruption מתחיל לרוב כ-DoS לפני שהופך ל-RCE יציב.
- [ ] מעקב אחר **CISA ICS Medical Advisories (ICSMA)** כערוץ קבוע.
- [ ] הצלבת מלאי המכשירים מול קטלוג ה-**KEV** של CISA.

---

## 9. מקורות

**DICOM / PACS**
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

**HL7 / FHIR / אינטגרציה**
- [CVE-2023-43208 (Mirth Connect RCE): Analysis & Detection — Huntress](https://www.huntress.com/threat-library/vulnerabilities/cve-2023-43208)
- [Critical NextGen Healthcare Mirth Connect Vulnerability Under Active Exploitation — HIPAA Journal](https://www.hipaajournal.com/critical-nextgen-healthcare-mirth-connect-under-active-exploitation/)
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
- [CVE-2026-56445: Unauthenticated Arbitrary File Write in pynetdicom](https://www.machinespirits.com/advisory/1f9f99/)
- [CVE-2026-50003: DCMTK Path Traversal — SentinelOne](https://www.sentinelone.com/vulnerability-database/cve-2026-50003/)
- [High-Severity Vulnerability Identified in OHIF Viewers DICOM — HIPAA Journal](https://www.hipaajournal.com/high-severity-vulnerability-identified-in-ohif-viewers-dicom/)

**סטטיסטיקה ומגמות**
- [Healthcare Cybersecurity Statistics 2026 — ORDR](https://ordr.net/blog/healthcare-cybersecurity-statistics-2026-report)
- [Healthcare Cybersecurity 2026: Threats and How to Stop Them — CybelAngel](https://cybelangel.com/blog/healthcare-industry-guide-cyber/)
- [Ransomware in Healthcare 2026: The Attack Timeline — CybelAngel](https://cybelangel.com/blog/ransomware-in-healthcare-attack-timeline/)
- [Threats and Security Strategies for IoMT Infusion Pumps — arXiv](https://arxiv.org/pdf/2509.14604)
