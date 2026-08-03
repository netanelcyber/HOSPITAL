# Run results — SUSP-BIO-04 verification attempt

**Date:** 2026-08-03
**Environment:** Ubuntu 24.04, clang 18.1.3, libFuzzer + ASan + UBSan, 4 cores.
**Pinned targets:** OpenJPEG `v2.5.3` (`210a8a5`), GDCM `v3.0.24` (`2eaae20`).

> **Bottom line:** the harness works end-to-end, but **no novel vulnerability was
> confirmed**. SUSP-BIO-04 (memory-corruption / RCE in the JPEG2000 decode path)
> is **still unverified** — not disproven, just not reproduced in short runs. One
> signal appeared (a GDCM allocation-DoS) but it matches an **already-known CVE
> class**, so nothing here is reportable. Honest status: keep hunting, don't disclose.

## What actually happened

### 1. Pipeline validated ✅
Both harnesses build, run, accumulate coverage, and the crash → reproduce →
minimize → classify (`triage.sh`) path works. OpenJPEG harness sustained
~6,600 exec/s; from an empty corpus libFuzzer self-grew a 53-unit corpus and
reached cov 1106 in 30s with **zero crashes**.

### 2. One UBSan false positive — fixed, not a bug ⚠️
First OpenJPEG run aborted immediately on `-fsanitize=function`
(function-pointer *type* mismatch in OpenJPEG's opaque-handle C API). This is a
**known false-positive class**, not memory unsafety. Fix: build with
`-fno-sanitize=function` (now the default in `build.sh`), matching OSS-Fuzz.
After the fix, OpenJPEG ran clean.

### 3. One GDCM allocation-DoS — real behavior, but NOT novel ⚠️
The GDCM harness hit an out-of-memory on a **163-byte** input:

```
malloc(4286906368)  ~= 4.29 GB
  gdcm::ByteValue::SetLength(gdcm::VL)             gdcmByteValue.cxx:44   (eager new[])
  gdcm::ExplicitImplicitDataElement::ReadPreValue  reads element length (VL) from stream
  gdcm::Reader::Read()
```

GDCM reads a DICOM data-element length field and allocates a buffer of that size
**before validating it against the remaining stream length** — an uncontrolled
memory allocation (CWE-789 / CWE-400).

**Why this is not reported:**
- It matches the **already-disclosed GDCM allocation-DoS**, CVE-2026-3650, whose
  public description is literally "~150 bytes → up to 4.2 GB." 163 bytes → 4.29 GB
  is the same class. Filing it would be a **duplicate**.
- It is an **OOM (denial of service), not memory corruption** — no ASan
  heap-overflow/UAF — so it is not the RCE-class bug SUSP-BIO-04 targets.

### 4. SUSP-BIO-04 itself: NOT reproduced (and why the run was shallow)
The JPEG2000 *decode* path was barely exercised, for a concrete reason:

- **No JPEG2000 seed corpus was available.** The shallow git clones do not include
  OpenJPEG's/GDCM's test-image submodules, and no image tooling (Pillow/opj_compress)
  was on hand to synthesize J2K. So the OpenJPEG harness fuzzed from scratch (weak
  coverage of deep codec code), and the GDCM harness mostly exercised the **DICOM
  parser front-end** — which is where the known allocation-DoS lives — rather than
  reaching `gdcm::JPEG2000Codec`.
- Short wall-clock (seconds–minutes). Real memory-corruption hunting on a mature
  codec needs a **good J2K seed corpus + hours-to-days** of coverage-guided fuzzing.

## To actually pursue SUSP-BIO-04 next

1. **Get real seeds** (the single biggest lever): full (non-shallow) OpenJPEG/GDCM
   clones with their test-data submodules, or generate J2K/J2K-encapsulated-DICOM
   with `opj_compress` / `gdcmconv --j2k`. Put them in `corpus/`.
2. **Separate OOMs from corruption:** run with `-malloc_limit_mb=512` so the known
   allocation-DoS is flagged and skipped, letting the fuzzer keep hunting for real
   memory-corruption instead of stopping on the first OOM. (Now wired into `run.sh`
   via the `MALLOC_LIMIT_MB` knob.)
3. **Run long:** hours per target, ideally parallel (`-jobs -workers`), and reuse the
   grown corpus across runs.
4. Only a **reproducible ASan heap-overflow/UAF on the pinned-latest** that survives
   minimization and is **not** already a known CVE becomes a real finding → then, and
   only then, the disclosure workflow in `../docs/`.

## Nothing was disclosed
No report was sent to any vendor or CERT. No crash input is committed. The only
outputs are this summary and the tooling.
