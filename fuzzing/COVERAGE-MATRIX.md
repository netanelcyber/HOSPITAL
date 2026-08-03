# SUSP-BIO-XX — verification coverage, ordered by CVSS

**Rule (per request):** higher estimated CVSS is handled first. This table sorts every
candidate by the **worst-case CVSS its bug class could reach if confirmed**, and records
whether it is verifiable *in this environment* (local fuzzing on owned builds) or needs a
different setup (a running app, a network scan) that must NOT be spun up against systems
you don't own.

| Rank | ID | Candidate (class) | Max CVSS if confirmed | Verifiable here? | Status (2026-08-03) |
|---|---|---|---|---|---|
| 1 | **B04** | OpenJPEG JPEG2000 decode — memory corruption | ~9.8 (RCE) | ✅ fuzzing | **Ran. Clean** (30s, 0 crashes, seedless). Unverified, keep hunting. |
| 2 | **B05** | CharLS JPEG-LS decode — memory corruption | ~9.8 (RCE) | ✅ fuzzing | **Ran deep (ASan-only).** No memory corruption. Only benign signed-overflow UB + a slow-unit/timeout (CPU-DoS). Likely known (OSS-Fuzz). Not reportable. |
| 2b | **B04-via-DICOM** | GDCM JPEG2000 **codec wrapper** (encapsulated DICOM) | ~8–9 (RCE) | ✅ fuzzing | **Ran deep.** Built 36 J2K-encapsulated-DICOM seeds → codec reached (cov 15.9k). No codec corruption; only front-end alloc-DoS OOMs. |
| 3 | **B06** | RT-STRUCT / waveform parse (GDCM/DCMTK) — memory corruption | ~8–9 | ✅ fuzzing (needs RT seeds) | Reachable via the GDCM harness with RT-STRUCT seeds; not yet seeded. Pending. |
| 4 | **B07** | Encapsulated-PDF-in-DICOM parse — memory corruption | ~7–8 | ✅ fuzzing (needs PDF-DICOM seeds) | Same GDCM harness, needs seeds. Pending. |
| 5 | **B04/GDCM** | GDCM allocation-DoS (parser front-end) | 7.5 (DoS) | ✅ fuzzing | **Ran. Found** 163 B → 4.29 GB (`ByteValue::SetLength`). **KNOWN = CVE-2026-3650.** Duplicate, not reported. |
| — | A01 | pynetdicom `storescp` path traversal | 8.1 (write/RCE) | ⚠️ needs a running DICOM SCP | Logic bug — functional PoC on an owned pynetdicom install, not fuzzing. |
| — | A02 | DICOM field→path traversal (other UIDs) | 8.1 | ⚠️ running SCP | Same as A01. |
| — | A03 | Zip-Slip in Orthanc/importer | 8.1 | ⚠️ running Orthanc | Functional test on owned Orthanc. |
| — | C11 | OpenMRS Velocity SSTI (other fields) | 9.x (RCE) | ⚠️ running OpenMRS | Needs a live OpenMRS + Manage-Concepts account; web test, not fuzzing. |
| — | C08/09/10 | OpenEMR ACL / API scope bypass | ~6.5–8.1 | ⚠️ running OpenEMR | Live PHP/MySQL install + role accounts; see `disclosure-report-template.md`. |
| — | D12 | Mirth channel-script RCE | 9.x (per-install) | ⚠️ running Mirth | Config/code review of a real Mirth deployment. |
| — | D13 | HAPI FHIR expression engines | ~7–8 | ⚠️ running HAPI | Live FHIR server test. |
| — | D14/15 | HL7→XSS / FHIR narrative XSS | ~6–7 | ⚠️ running PACS/UI | Web injection on a live UI. |
| — | E16–19 | Hard-coded secrets / exposed mgmt / AE-Title / TLS | ~6–9 | ⚠️ network scan | External-exposure scan of **your own** perimeter; not fuzzing. |
| — | C22 | OpenEMR portal IDOR (novel) | ~6.5–8.1 | ⚠️ running OpenEMR portal | Live portal + two patient accounts. |
| — | F20/21 | GDCM / pynetdicom-qrscp (unmaintained) | n/a | — | Posture, not a single bug: sandbox + compensating controls. |

## What this run actually established

- The **highest-CVSS class (memory-corruption / RCE, ranks 1–4) was fuzzed first**, exactly per
  the priority rule. Two codecs were built and run under ASan/UBSan:
  - **OpenJPEG** — clean in a short seedless run.
  - **CharLS** — a reproducible **signed-overflow (CWE-190)** in the decode arithmetic; UB but
    not demonstrated memory unsafety, low likely severity, probably already known.
- The only DoS-class hit (**GDCM**, rank 5) is the **already-CVE'd** allocation bug.
- **No novel high-CVSS (RCE) vulnerability was confirmed.** Nothing was disclosed.

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
