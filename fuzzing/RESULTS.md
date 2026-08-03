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

### 5. CharLS / JPEG-LS (SUSP-BIO-05): signed-overflow, low impact, likely known ⚠️
Added `harness_charls.cxx` and ran it against CharLS `2.4.2` with its 29 shipped
`.jls` conformance seeds. It hit a **UBSan signed-integer-overflow (CWE-190)**:

```
default_traits.hpp:168  dequantize(int):  error_value * (2*near_lossless+1)  overflows int
  compute_reconstructed_sample
  scan_decoder_core::decode_run_interruption_pixel   (JPEG-LS run mode)
  ... jpegls_decoder::decode()
```

This is genuine, reachable decode-path UB (not a harness artifact). **But:**
- It is **signed-overflow UB, not memory corruption** — no ASan heap error. The
  overflowed value flows into `fix_reconstructed_value`, which clamps to a valid
  sample, so the likely effect is a wrong pixel, not an OOB access. Probable
  severity: **low** (CVSS low / possibly non-security).
- CharLS is on **OSS-Fuzz** with an active maintainer, so this is **plausibly
  already known**. Must be deduped against CharLS issues/OSS-Fuzz before any contact.

Per the CVSS-priority rule this does **not** jump the queue — it is not the
RCE-class bug the memory-corruption hunt targets. Not reported.

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

## Deeper run (seeded + guarded, value-profile)

Follow-up to go deeper on the top-CVSS target (OpenJPEG, B04):

1. **Real corpus.** Built `opj_compress` and generated 72 valid J2K/JP2 seeds from
   21 synthetic PNM images (8/16-bit, gray/RGB, varied sizes; tiled, multi-resolution,
   lossless, progression orders). Coverage went **1,106 → 14,147 edges (~13×)**; a
   30-min run grew the corpus to **2,887 units / 94 MB**.

2. **OOM triage — benign, known class.** Every crash artifact was an OOM or slow-unit,
   never memory corruption. Representative OOM: `malloc(5.57 GB)` at
   `opj_j2k_update_image_data` (j2k.c:10395) — a buffer sized from attacker-controlled
   `width*height*components`. The full size is requested (no integer-overflow-to-small),
   so it is the **known JPEG2000 decompression-bomb DoS**, not an exploitable primitive.

3. **Harness dimension guard (real improvement).** Those OOMs were killing workers and
   starving the decode logic. Added a post-`read_header` guard in `harness_openjpeg.c`
   that skips images whose `w*h*components` exceeds 64M samples (mirrors OSS-Fuzz). Effect:
   workers stop dying on bombs and **exec/s rose ~38 → ~341 (≈9×)**, so the fuzzer now
   spends its time in the codec (where OOB/UAF would surface), not the allocator.

4. **Deeper campaign** relaunched with the guard, the grown corpus, `-use_value_profile=1`,
   and no malloc-abort. Result recorded in this file when it completes.

Status so far: still **no memory-corruption** in OpenJPEG — only the known allocation-DoS
class. That is a legitimate (negative) result at this coverage depth, not a confirmed bug.

## Parallel deepening — three codecs at once

Ran the top-CVSS memory-corruption class across three targets concurrently
(oversubscribed on 4 cores, per request for breadth):

### OpenJPEG (B04) — guarded + value-profile
Grown corpus (2,887 units) + dimension guard + `-use_value_profile=1`. exec/s ~341.
Only artifacts: `slow-unit`s (slow decode, CPU-DoS-ish) — **no memory corruption**.

### GDCM JPEG2000 wrapper (B04-via-DICOM) — the realistic path, now actually reached
The earlier GDCM run only hit the DICOM parser front-end. To reach
`gdcm::JPEG2000Codec`, wrapped 36 real J2K codestreams into **minimal encapsulated
DICOM** (Python: parse each codestream's SIZ marker for true rows/cols/components/bit-depth,
emit file-meta with TS `1.2.840.10008.1.2.4.90/.91` + encapsulated PixelData). Validated:
coverage jumped to **15,883 edges / 41,534 features**, all 36 decode — the codec path is
genuinely exercised. Deep run artifacts: **only `oom`** = the already-known allocation-DoS
(CVE-2026-3650 class) in the parser front-end; **no codec memory corruption**. Ran with
`-jobs=40` so workers self-restart past those benign OOMs.

### CharLS JPEG-LS (B05) — ASan-only to separate UB from corruption
The `undefined` build kept halting on **signed-integer-overflow** in decode arithmetic
(`default_traits.hpp:168` `dequantize`, then `run_mode_context.hpp:43`) — benign,
non-corruption UB, and CharLS is actively OSS-Fuzzed. Rebuilt **ASan-only** to hunt purely
for memory unsafety. Result: no ASan error — only a **timeout** (a ~1 MB stream that decodes
very slowly in `read_unary_code`, a CPU-DoS/hang class). **No memory corruption.**

### Net result of the parallel hunt
OpenJPEG and CharLS: no memory-corruption (only DoS-class artifacts + benign arithmetic UB).

**GDCM codec path — one genuine memory-safety bug found.** Once the J2K-encapsulated-DICOM
seeds drove mutations into `gdcm::JPEG2000Codec`, the fuzzer produced a **reproducible ASan
heap-buffer-overflow (out-of-bounds READ, CWE-125) in GDCM's JPEG2000 header/marker parser**
(`parsej2k_imp` / `read16`, reached via `ImageReader` on a malformed encapsulated JPEG2000
codestream). Two independent inputs trigger it; confirmed on GDCM v3.0.24.

Severity is Medium (an OOB **read** → heap info-leak / crash, not a demonstrated write/RCE).

**Novelty is PLAUSIBLE but unconfirmed.** The known GDCM OOB-read CVEs are in *other* codecs
(`RAWCodec`, `RLECodec`, `JPEGBITSCodec`) and in the JPEG2000 *decode* path
(`DecodeByStreamsCommon`, CVE-2024-22391) — none matched this *header-parser* site in searches.
That is suggestive, not proof.

**Responsible-disclosure hold:** the full technical writeup, root cause, and the reproducer are
**kept local and NOT committed** to this (possibly public) repo — same principle as never
committing crash inputs. They will move only through coordinated disclosure (GDCM maintainer
historically unresponsive → CERT/CC + CISA), and only after dedup against GDCM's tracker and
Cisco Talos's advisory queue confirms it is not already reported. Nothing has been disclosed
or published yet.

Also observed (lower value, DoS-class): four GDCM front-end aborts (uncaught exception on
malformed file-meta / data elements) — robustness issues, not memory corruption.

## Nothing was disclosed
No report was sent to any vendor or CERT. No crash input is committed. The only
outputs are this summary and the tooling.
