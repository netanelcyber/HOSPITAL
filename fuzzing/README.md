# Fuzzing harness — verify SUSP-BIO-04 (JPEG2000 decode memory-corruption)

Purpose: turn the **unverified** hypothesis `SUSP-BIO-04`
(`../docs/suspected-cve-candidates.md`) into a **real, reproducible crash** on code you
build yourself — *before* anything is disclosed to any vendor or CERT.

> ⚠️ **Authorization & scope**
> - Everything here compiles and fuzzes **open-source code on your own machine**. No live
>   system, hospital network, or third-party server is touched.
> - **No exploit/PoC is published.** Crash inputs are `.gitignore`d and never committed —
>   they are exploit primitives and go only into a private, coordinated disclosure.
> - This proves *whether* a bug exists. It does **not** authorize testing anyone else's
>   deployment.

## What it targets and why

| Target | Why | A crash here is reported to |
|---|---|---|
| **OpenJPEG** (`uclouvain/openjpeg`) | the actual JPEG2000 codec | GitHub advisory / MITRE (CNA-LR) |
| **GDCM** (`malaterre/GDCM`) | openly embeds OpenJPEG via `gdcm::JPEG2000Codec`; catches DICOM-wrapper bugs too | CERT/CC (maintainer historically unresponsive) + CISA |

**DCMTK is intentionally not fuzzed for JPEG2000** — core DCMTK ships no JPEG2000 (that's the
commercial JasPer-based DCMJP2K module), so it's the wrong target for this codec. The DCMTK
angle belongs to a separate **CharLS / JPEG-LS** harness (`SUSP-BIO-05`).

## Quick start (Docker — recommended, fully isolated)

```bash
# from the repo root
docker build -t biofuzz fuzzing/
docker run --rm -it -v "$PWD/fuzzing/out:/work/out" biofuzz

# inside the container:
./run.sh openjpeg      # or: ./run.sh gdcm
# ... let it run; crashes land in ./crashes/ ...
./triage.sh crashes/crash-<hash>
cat out/versions.txt   # exact pinned SHAs for the disclosure "version tested" field
```

## Bumping to the pinned-latest before a real hunt

A crash only counts if it reproduces on the **current** release (otherwise it may be an
already-fixed duplicate). Before a serious run, edit the `ARG OPENJPEG_TAG` / `ARG GDCM_TAG`
lines in the `Dockerfile` to the latest release tags, rebuild, and confirm `out/versions.txt`
shows the SHAs you expect.

## Files

| File | Role |
|---|---|
| `Dockerfile` | clang + sanitizers + pinned OpenJPEG & GDCM sources |
| `build.sh` | builds both libraries + harnesses with `-fsanitize=fuzzer,address,undefined` |
| `harness_openjpeg.c` | libFuzzer entrypoint → decode buffer via OpenJPEG memory stream |
| `harness_gdcm.cxx` | libFuzzer entrypoint → `gdcm::ImageReader` + forced pixel decode |
| `corpus/` | seed inputs (valid J2K / J2K-encapsulated DICOM) — provenance in `corpus/README.md` |
| `run.sh` | launches a chosen harness with sane flags + `crashes/` artifact dir |
| `triage.sh` | symbolizes the ASan/UBSan stack, minimizes the input, tags the owning component |

## From crash → disclosure (do NOT skip triage)

1. `triage.sh` tells you the **owning component** (OpenJPEG vs GDCM wrapper) and a **CWE guess**
   (e.g. CWE-787 out-of-bounds write, CWE-125 out-of-bounds read).
2. Fill `../docs/disclosure-report-template.md` with: pinned version+SHA (`out/versions.txt`),
   the minimized input description (not the raw bytes in public), the sanitized stack, CWE, and a
   CVSS vector.
3. Route per `../docs/suspected-cve-candidates.md` → "Responsible Disclosure":
   - bug in **OpenJPEG** → GitHub advisory on `uclouvain/openjpeg`; if private reporting is
     disabled, **MITRE** (`cveform.mitre.org`).
   - bug in **GDCM** → **CERT/CC (VINCE)**, `kb.cert.org/vuls/report` (maintainer unresponsive).
   - either → **CISA** (`cisa.gov/report`) for the medical-imaging coordination + ICSMA.
   - if it reproduces against an **Israel-deployed PACS** (e.g. an embedding vendor) → also
     **CERT-IL** (`report@cyber.gov.il`, tel. 119). See `../docs/israel-relevance.md`.
4. Give a fix window (~90 days upstream; CERT/CC ~45, extended for multi-party). **No public PoC**
   until fixes ship across the downstream (this bug cascades into many commercial PACS).
