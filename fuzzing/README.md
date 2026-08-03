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

# Do NOT bind-mount over /work/out — the image builds fuzz_openjpeg/fuzz_gdcm/
# fuzz_charls and versions.txt there, and mounting an empty host dir hides them
# (run.sh would then report "not built"). Mount dedicated host dirs for the
# artifacts you want to KEEP after the --rm container exits: the per-target crash
# dirs and the corpus (run.sh writes reproducers to crashes_<target>/ and grows
# corpus/ in place; both are lost with the container otherwise).
mkdir -p fuzzing/persist/corpus fuzzing/persist/crashes_openjpeg
docker run --rm -it \
    -v "$PWD/fuzzing/persist/corpus:/work/corpus" \
    -v "$PWD/fuzzing/persist/crashes_openjpeg:/work/crashes_openjpeg" \
    biofuzz

# inside the container (both harness binaries exist, so name the target explicitly):
./run.sh openjpeg      # or: ./run.sh gdcm | ./run.sh charls
# ... let it run; crashes land in ./crashes_openjpeg/ ...
./triage.sh openjpeg crashes_openjpeg/crash-<hash>   # target is REQUIRED here
cat out/versions.txt   # pinned SHAs for the disclosure "version tested" field
```
> To keep GDCM/CharLS artifacts too, add `-v .../crashes_gdcm:/work/crashes_gdcm`
> (and `crashes_charls`) mounts. Never commit crash inputs to git — persist them
> to a host dir only, for private disclosure.

## ⚠️ Seeds matter more than anything (read before a real hunt)

A first live run (see `RESULTS.md`) confirmed the pipeline works but reached the
JPEG2000 **decode** path only shallowly, because **no JPEG2000 seed corpus was
present** — shallow clones omit the upstream test-image submodules. Without J2K
seeds:
- the OpenJPEG harness fuzzes from scratch (weak deep-codec coverage), and
- the GDCM harness mostly exercises the DICOM **parser front-end** (where a
  *known* allocation-DoS lives, CVE-2026-3650) rather than `gdcm::JPEG2000Codec`.

Before a serious hunt, populate `corpus/` with real J2K. Note the image's
`build.sh` sets `BUILD_CODEC=OFF` / `GDCM_BUILD_APPLICATIONS=OFF`, so
`opj_compress`/`gdcmconv` are **not** in the image, and a plain non-shallow clone
does **not** fetch submodules. Use one of these that actually works:
```bash
# (a) get the upstream conformance test data (submodules, recursively):
git clone --recurse-submodules https://github.com/uclouvain/openjpeg.git
git clone --recurse-submodules https://github.com/malaterre/GDCM.git   # includes gdcmData
#     then copy their *.j2k / *.jp2 / *.dcm into corpus/

# (b) or build the generators yourself (outside the fuzz image), then encode:
#     cmake -DBUILD_CODEC=ON ... openjpeg  -> opj_compress -i input.pnm -o seed.j2k
#     cmake -DGDCM_BUILD_APPLICATIONS=ON ... GDCM -> gdcmconv --j2k in.dcm seed.dcm
```
The reference run generated seeds via method (b) built separately — the fuzz
image itself cannot produce them.

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
