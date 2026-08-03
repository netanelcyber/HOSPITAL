# SUSP-BIO-XX — verification coverage, ordered by CVSS

**Rule (per request):** higher estimated CVSS is handled first. This table sorts every
candidate by the **worst-case CVSS its bug class could reach if confirmed**, and records
whether it is verifiable *in this environment* (local fuzzing on owned builds) or needs a
different setup (a running app, a network scan) that must NOT be spun up against systems
you don't own.

| Rank | ID | Candidate (class) | Max CVSS if confirmed | Verifiable here? | Status (2026-08-03) |
|---|---|---|---|---|---|
| 1 | **B04** | OpenJPEG JPEG2000 decode — memory corruption | ~9.8 (RCE) | ✅ fuzzing | **Ran — no ASan failure observed** (0 crashes across the recorded runs). A finite campaign can't prove absence of bugs; keep hunting. |
| 2 | **B05** | CharLS JPEG-LS decode — memory corruption | ~9.8 (RCE) | ✅ fuzzing | **Ran deep (ASan-only).** No memory corruption. Only benign signed-overflow UB + a slow-unit/timeout (CPU-DoS). Likely known (OSS-Fuzz). Not reportable. |
| 2b | **B04-via-DICOM** | GDCM JPEG2000 **codec wrapper** (encapsulated DICOM) | ~8–9 (RCE) | ✅ fuzzing | **Ran deep → FOUND a genuine ASan heap OOB-READ (CWE-125)** in GDCM's JPEG2000 header parser (`parsej2k_imp`), reproducible on v3.0.24. Severity Medium (read/info-leak, not RCE). **Novelty plausible, unconfirmed** — details+repro held PRIVATE pending dedup + coordinated disclosure (CERT/CC + CISA). |
| 3 | **B06** | RT-STRUCT / waveform parse (GDCM/DCMTK) — memory corruption | ~8–9 | ✅ fuzzing (needs RT seeds) | Reachable via the GDCM harness with RT-STRUCT seeds; not yet seeded. Pending. |
| 4 | **B07** | Encapsulated-PDF-in-DICOM parse — memory corruption | ~7–8 | ⚠️ needs a DIFFERENT harness | **NOT covered by `harness_gdcm.cxx`** — it uses `ImageReader`/`GetBuffer` (Pixel Data path), while an encapsulated PDF is stored as an *encapsulated document*, not Pixel Data, and no PDF parser is invoked. Needs a viewer or a dedicated embedded-document harness. Pending. |
| 5 | **B04/GDCM** | GDCM allocation-DoS (parser front-end) | 7.5 (DoS) | ✅ fuzzing | **Ran. Found** 163 B → 4.29 GB (`ByteValue::SetLength`). **KNOWN = CVE-2026-3650.** Duplicate, not reported. |
> **Reading the `Rank` column:** ranks 1–5 are the locally-fuzzable memory-corruption class, ordered by CVSS. The rows below with `—` are **not lower severity** — several are higher — they are only **not verifiable in this local fuzzing environment** (they need a running app/network). By pure CVSS-priority the order would be: **C11 OpenMRS SSTI (9.x) and D12 Mirth (9.x) FIRST**, then B04/B05 (9.8), then the rest. They sit below only because feasibility ≠ severity; when an environment is available, tackle the 9.x app candidates before the medium-severity fuzz leftovers.

| — | **C11** | OpenMRS Velocity SSTI (other fields) | **9.x (RCE)** | ⚠️ running OpenMRS | **Highest CVSS overall.** Needs a live OpenMRS + Manage-Concepts account; web test, not fuzzing. |
| — | **D12** | Mirth custom channel-script RCE | **9.x (per-install)** | ⚠️ running Mirth | **Highest CVSS overall**, but this is **deployment code**, not a Mirth product CVE — internal secure-code audit, not upstream disclosure. |
| — | A01 | pynetdicom `storescp` path traversal | 8.1 (write/RCE) | ⚠️ needs a running DICOM SCP | Logic bug — functional PoC on an owned pynetdicom install, not fuzzing. |
| — | A02 | DICOM field→path traversal (other UIDs) | 8.1 | ⚠️ running SCP | Same as A01. |
| — | A03 | Zip-Slip in Orthanc/importer | 8.1 | ⚠️ running Orthanc | Functional test on owned Orthanc. |
| — | C08/09/10 | OpenEMR ACL / API scope bypass | ~6.5–8.1 | ⚠️ running OpenEMR | Live PHP/MySQL install + role accounts; see `disclosure-report-template.md`. |
| — | D13 | HAPI FHIR expression engines | ~7–8 | ⚠️ running HAPI | Live FHIR server test. |
| — | D14/15 | HL7→XSS / FHIR narrative XSS | ~6–7 | ⚠️ running PACS/UI | Web injection on a live UI. |
| — | E16–19 | Hard-coded secrets / exposed mgmt / AE-Title / TLS | ~6–9 | ⚠️ network scan | External-exposure scan of **your own** perimeter; not fuzzing. |
| — | C22 | OpenEMR portal IDOR (novel) | ~6.5–8.1 | ⚠️ running OpenEMR portal | Live portal + two patient accounts. |
| — | F20/21 | GDCM / pynetdicom-qrscp (unmaintained) | n/a | — | Posture, not a single bug: sandbox + compensating controls. |

## What this run actually established

- The **locally-fuzzable memory-corruption class was fuzzed first**, per the priority rule.
  Three codecs were built and run under ASan/UBSan:
  - **OpenJPEG** — no ASan memory-corruption failure observed in the recorded runs (not a proof of absence).
  - **CharLS** — a reproducible **signed-overflow (CWE-190)** in the decode arithmetic; UBSan-only
    finding, no ASan memory error. **Left UNRESOLVED, not "benign"** — ASan does not diagnose
    arithmetic UB, and optimization may rely on no-overflow; needs a fix or a recovering-UBSan
    analysis before any safety claim. Likely known (OSS-Fuzz).
- **Two distinct GDCM hits — do not conflate them:**
  1. **Genuine memory-safety bug (row 2b):** a reproducible **heap OOB READ (CWE-125)** in the
     JPEG2000 header parser `parsej2k_imp`, Medium severity, confirmed on v3.0.24 **and master**;
     plausibly new; held private for coordinated disclosure. This is the one real finding.
  2. **Known allocation-DoS (row 5):** the already-CVE'd `ByteValue::SetLength` OOM (CVE-2026-3650).
- **No RCE was demonstrated**, and the OOB read proves invalid memory access, not (by itself)
  that data reaches an attacker. Nothing was disclosed.

## Why the rest can't be "run" here

Ranks below the line are **not memory-fuzzing targets**. Verifying them means standing up a live,
vulnerable service (OpenEMR, OpenMRS, Mirth, HAPI FHIR, Orthanc, a PACS) or scanning a network
perimeter. Doing that responsibly requires **your** authorized, owned instances — it must not be
pointed at third-party systems. For those, the right artifacts are already in `../docs/`:
`disclosure-report-template.md` (web/logic findings) and `suspected-cve-candidates.md`
(per-candidate verification method + reporting route).

## Highest-value next steps (still CVSS-ordered)

1. **B04/B05 done right** — real J2K/JLS seed corpora + hours of fuzzing (biggest lever for the
   top-CVSS RCE class). Add `-jobs/-workers`, reuse grown corpus.
2. **B06/B07** — add RT-STRUCT and encapsulated-PDF DICOM seeds to reach those parser paths.
3. Triage the **CharLS overflow** against CharLS's issue tracker / OSS-Fuzz before any contact —
   if it's genuinely new *and* shown to reach memory, only then it climbs the queue.
4. For ranks below the line, verify on **owned** app/network instances using the docs above.
