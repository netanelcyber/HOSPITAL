#!/usr/bin/env bash
#
# Triage a crash reproducer:
#   1) re-run it under the harness to capture a symbolized ASan/UBSan stack
#   2) minimize the input
#   3) classify the owning component (OpenJPEG vs GDCM wrapper)
#   4) emit a triage stub to seed the disclosure report
#
#   ./triage.sh {openjpeg|gdcm} crashes/crash-<hash>
#   ./triage.sh crashes/crash-<hash>          # target inferred if only one bin exists
#
# Output: out/triage-<hash>.txt  (+ a minimized input alongside the original)
#
set -euo pipefail

WORK_DIR="${WORK_DIR:-/work}"
OUT_DIR="${WORK_DIR}/out"

# --- resolve args ------------------------------------------------------------
if [ $# -eq 2 ]; then
    target="$1"; crash="$2"
elif [ $# -eq 1 ]; then
    crash="$1"
    # Infer only when EXACTLY ONE of the three harnesses is built (count them all).
    present=()
    [ -x "${OUT_DIR}/fuzz_openjpeg" ] && present+=(openjpeg)
    [ -x "${OUT_DIR}/fuzz_gdcm" ]     && present+=(gdcm)
    [ -x "${OUT_DIR}/fuzz_charls" ]   && present+=(charls)
    if [ "${#present[@]}" -eq 1 ]; then
        target="${present[0]}"
    else
        echo "error: ${#present[@]} harnesses present (${present[*]:-none}); specify target: $0 {openjpeg|gdcm|charls} <crash>" >&2
        exit 2
    fi
else
    echo "usage: $0 {openjpeg|gdcm|charls} <crash-file>" >&2
    exit 2
fi

case "${target}" in
    openjpeg) bin="${OUT_DIR}/fuzz_openjpeg" ;;
    gdcm)     bin="${OUT_DIR}/fuzz_gdcm" ;;
    charls)   bin="${OUT_DIR}/fuzz_charls" ;;
    *) echo "error: unknown target '${target}'" >&2; exit 2 ;;
esac
[ -x "${bin}" ] || { echo "error: ${bin} not built" >&2; exit 1; }
[ -f "${crash}" ] || { echo "error: no such crash file: ${crash}" >&2; exit 1; }

hash="$(basename "${crash}")"
report="${OUT_DIR}/triage-${hash}.txt"
mkdir -p "${OUT_DIR}"

export ASAN_OPTIONS="${ASAN_OPTIONS:-abort_on_error=1:allocator_may_return_null=1:detect_leaks=0}"
export UBSAN_OPTIONS="${UBSAN_OPTIONS:-print_stacktrace=1:halt_on_error=1}"

# Preserve the campaign's timeout AND allocation limit so replay reproduces the
# same failure the campaign recorded. run.sh defaults to -timeout=25 and
# MALLOC_LIMIT_MB=512; libFuzzer's malloc_limit otherwise defaults to rss_limit
# (2048 MiB here), so an OOM artifact for a 512 MiB–2 GiB request would NOT
# reproduce and the reproduction guard below would wrongly reject it. Override
# via TIMEOUT_SEC / MALLOC_LIMIT_MB if your campaign used other values.
TIMEOUT_SEC="${TIMEOUT_SEC:-25}"
MALLOC_LIMIT_MB="${MALLOC_LIMIT_MB:-512}"
lim_args=(-timeout="${TIMEOUT_SEC}" -rss_limit_mb=2048)
[ "${MALLOC_LIMIT_MB}" != "0" ] && lim_args+=(-malloc_limit_mb="${MALLOC_LIMIT_MB}")

echo "==> Reproducing under ${target} to capture sanitizer stack"
san_log="${OUT_DIR}/san-${hash}.log"
# Single-shot replay of the crash input; capture the sanitizer report.
set +e
"${bin}" "${lim_args[@]}" "${crash}" > "${san_log}" 2>&1
rc=$?
set -e

# Abort if the input does NOT reproduce a real failure — a stale/mis-targeted
# artifact must not be dressed up as a completed triage. Accept only a sanitizer
# error or a libFuzzer timeout/oom as evidence of reproduction.
if [ "${rc}" -eq 0 ] || ! grep -Eqi 'ERROR: (AddressSanitizer|libFuzzer)|runtime error:|SUMMARY: (AddressSanitizer|UndefinedBehaviorSanitizer|libFuzzer)' "${san_log}"; then
    echo "==> NOT REPRODUCED (exit ${rc}); no sanitizer/timeout/oom diagnostic in ${san_log}." >&2
    echo "    The input may be stale (rebuild) or replayed against the wrong harness. Aborting triage." >&2
    exit 3
fi

echo "==> Minimizing input (crash-signature-preserving)"
min="${crash}.min"
# dedup_token_length=3 makes -minimize_crash keep the SAME crash signature rather
# than drifting to a different defect an input might also trigger (observed in
# practice — a drifted 132B min reproduced a different crash than the 784B input).
set +e
ASAN_OPTIONS="${ASAN_OPTIONS}:dedup_token_length=3" \
"${bin}" -minimize_crash=1 -runs=20000 "${lim_args[@]}" \
    -exact_artifact_path="${min}" "${crash}" >> "${san_log}" 2>&1
set -e

# Re-validate: the minimized file must still reproduce the SAME owning frame as
# the original replay. If it drifted (or produced nothing), fall back to the
# original input so the report never pairs one defect's CWE with another's repro.
orig_top="$(grep -E '#0 0x' "${san_log}" | head -n1 | sed -E 's/.* in ([^ ]+).*/\1/')"
if [ -f "${min}" ]; then
    min_log="${OUT_DIR}/san-${hash}.min.log"
    set +e
    "${bin}" "${lim_args[@]}" "${min}" > "${min_log}" 2>&1
    set -e
    min_top="$(grep -E '#0 0x' "${min_log}" | head -n1 | sed -E 's/.* in ([^ ]+).*/\1/')"
    if [ -z "${min_top}" ] || { [ -n "${orig_top}" ] && [ "${min_top}" != "${orig_top}" ]; }; then
        echo "==> Minimized input drifted (top frame '${min_top}' != '${orig_top}'); using ORIGINAL as reproducer." >&2
        min="${crash}"
    fi
else
    min="${crash}"   # minimization produced nothing
fi

# --- classify owning component from the TOP faulting frame -------------------
# Ownership must come from which component owns the nearest-to-#0 application
# frame, not from mere keyword coexistence: a GDCM wrapper bug and an embedded
# OpenJPEG frame can both appear in one stack. Walk frames #0.. in order and take
# the first that names a known component; report ambiguity if unclear.
first_component() {
    # emit the owning component of the earliest matching stack frame
    grep -E '#[0-9]+ 0x' "${san_log}" | while read -r line; do
        case "${line}" in
            *openjp2*|*/openjpeg/*|*" opj_"*) echo "OpenJPEG"; return 0 ;;
            *charls::*|*/charls/*|*libcharls*) echo "CharLS"; return 0 ;;
            *gdcm::*|*/gdcm/*|*libgdcm*)       echo "GDCM"; return 0 ;;
        esac
    done
}
component="$(first_component | head -n1)"
[ -z "${component}" ] && component="unknown (inspect stack manually)"
# If both GDCM and OpenJPEG appear anywhere, flag the wrapper-vs-codec ambiguity.
if grep -Eiq 'gdcm::|/gdcm/|libgdcm' "${san_log}" && grep -Eiq 'openjp2|opj_|/openjpeg/' "${san_log}"; then
    component="${component} (GDCM+OpenJPEG both present — confirm top frame: wrapper bug vs embedded codec)"
fi

# --- guess CWE from the sanitizer verb --------------------------------------
cwe="(inspect stack)"
grep -qi 'WRITE of size'           "${san_log}" && cwe="CWE-787 Out-of-bounds Write"
grep -qi 'READ of size'            "${san_log}" && cwe="CWE-125 Out-of-bounds Read"
grep -qi 'heap-use-after-free'     "${san_log}" && cwe="CWE-416 Use After Free"
grep -qi 'attempting double-free'  "${san_log}" && cwe="CWE-415 Double Free"
grep -qi 'allocation-size-too-big\|out-of-memory' "${san_log}" && cwe="CWE-789 Memory Allocation with Excessive Size Value"
grep -qi 'runtime error:.*overflow' "${san_log}" && cwe="CWE-190 Integer Overflow (UBSan)"

top_frames="$(grep -E '#[0-9]+ 0x' "${san_log}" | head -n 8 || true)"

{
    echo "# Triage — ${hash}"
    echo
    echo "Harness:            ${target}"
    echo "Reproducer exit:    ${rc} (non-zero => reproduced)"
    echo "Minimized input:    ${min}"
    echo "Owning component:   ${component}"
    echo "CWE (guess):        ${cwe}"
    echo
    echo "Pinned versions (paste into report 'version tested'):"
    sed 's/^/    /' "${OUT_DIR}/versions.txt" 2>/dev/null || echo "    (versions.txt missing)"
    echo
    echo "Top stack frames:"
    if [ -n "${top_frames}" ]; then echo "${top_frames}" | sed 's/^/    /'; else echo "    (none captured — see ${san_log})"; fi
    echo
    echo "Full sanitizer log: ${san_log}"
    echo
    echo "Next: fill ../docs/disclosure-report-template.md and route per"
    echo "../docs/suspected-cve-candidates.md:"
    echo "  - OpenJPEG      -> GitHub advisory (uclouvain/openjpeg) or MITRE"
    echo "  - CharLS        -> GitHub private advisory (team-charls/charls) —"
    echo "                     active maintainer, on OSS-Fuzz; do NOT use the CISA path"
    echo "  - GDCM          -> CERT/CC (VINCE), maintainer unresponsive"
    echo "  - any           -> CISA (medical-imaging coordination), except CharLS"
    echo "  - IL-deployed   -> also CERT-IL (report@cyber.gov.il, tel 119)"
    echo
    echo "Do NOT publish the raw minimized input publicly until fixes ship downstream."
} | tee "${report}"

echo
echo "==> Triage written to ${report}"
