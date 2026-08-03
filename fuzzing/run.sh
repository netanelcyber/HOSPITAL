#!/usr/bin/env bash
#
# Launch a chosen harness under libFuzzer.
#
#   ./run.sh openjpeg [extra libFuzzer args...]
#   ./run.sh gdcm     [extra libFuzzer args...]
#
# Crashes are written to ./crashes/ (git-ignored). Corpus is grown in-place.
# Ctrl-C to stop. Examples:
#   ./run.sh openjpeg -max_total_time=600        # 10-minute smoke run
#   ./run.sh gdcm     -jobs=4 -workers=4          # parallel
#
set -euo pipefail

WORK_DIR="${WORK_DIR:-/work}"
OUT_DIR="${WORK_DIR}/out"
SEED_DIR="${WORK_DIR}/corpus"   # shared read-only seed set (mixed formats)

target="${1:-}"
shift || true

case "${target}" in
    openjpeg) bin="${OUT_DIR}/fuzz_openjpeg" ;;
    gdcm)     bin="${OUT_DIR}/fuzz_gdcm" ;;
    charls)   bin="${OUT_DIR}/fuzz_charls" ;;
    *)
        echo "usage: $0 {openjpeg|gdcm|charls} [libFuzzer args]" >&2
        exit 2
        ;;
esac

# Per-target crash dir so concurrently-fuzzed targets don't share a prefix —
# an artifact's owning harness must stay unambiguous for replay/triage.
CRASH_DIR="${WORK_DIR}/crashes_${target}"
# Per-target corpus so libFuzzer's coverage-interesting mutations grow into a
# dir private to this harness — otherwise each target pollutes the others'
# corpus with incompatible J2K/DICOM/JPEG-LS units and wastes startup rescanning
# them. Seed it once from the shared seed set (SEED_DIR is treated read-only).
CORPUS_DIR="${WORK_DIR}/corpus_${target}"

if [ ! -x "${bin}" ]; then
    echo "error: ${bin} not built. Run ./build.sh first." >&2
    exit 1
fi

mkdir -p "${CORPUS_DIR}" "${CRASH_DIR}"
# Merge the shared seed set into the per-target corpus on EVERY launch, no-clobber
# (-n): existing grown units are preserved, while seeds ADDED to corpus/ after an
# earlier campaign still reach the target. (An empty-only check would strand new
# seeds once the target corpus had any grown units.)
if [ -d "${SEED_DIR}" ]; then
    cp -an "${SEED_DIR}/." "${CORPUS_DIR}/" 2>/dev/null || true
fi

# Readable sanitizer stacks; keep going past a single fuzzer-managed timeout.
export ASAN_OPTIONS="${ASAN_OPTIONS:-abort_on_error=1:allocator_may_return_null=1:detect_leaks=0}"
export UBSAN_OPTIONS="${UBSAN_OPTIONS:-print_stacktrace=1:halt_on_error=1}"

# Single-allocation ceiling. IMPORTANT: -malloc_limit_mb does NOT skip an input
# and continue — per libFuzzer, "the fuzzer will exit if the target tries to
# allocate this number of Mb", writing an oom- artifact and terminating the
# process. GDCM's DICOM parser eagerly allocates multi-GB from an unvalidated
# element-length field (the KNOWN allocation-DoS, CVE-2026-3650 class), so in a
# single-process run this still stops the campaign on that known condition.
# The real fix is to filter/guard the known allocation IN THE HARNESS (as
# harness_openjpeg.c does for image dimensions); this cap only makes the OOM
# fast to spot. To survive it in a campaign, pair with -jobs=N so libFuzzer
# restarts a fresh worker after each OOM. Set MALLOC_LIMIT_MB=0 to disable.
MALLOC_LIMIT_MB="${MALLOC_LIMIT_MB:-512}"
malloc_arg=()
[ "${MALLOC_LIMIT_MB}" != "0" ] && malloc_arg=(-malloc_limit_mb="${MALLOC_LIMIT_MB}")

echo "==> Fuzzing '${target}'  (crashes -> ${CRASH_DIR})"
exec "${bin}" \
    -artifact_prefix="${CRASH_DIR}/" \
    -print_final_stats=1 \
    -timeout=25 \
    -rss_limit_mb=2048 \
    "${malloc_arg[@]}" \
    "$@" \
    "${CORPUS_DIR}"
