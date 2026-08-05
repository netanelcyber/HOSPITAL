#!/usr/bin/env bash
#
# Build OpenJPEG + GDCM and both libFuzzer harnesses, all instrumented with
# libFuzzer + AddressSanitizer + UndefinedBehaviorSanitizer.
#
# Designed to run inside the Docker image (sources at /src, work at /work), but
# honours SRC_DIR/WORK_DIR overrides so it can build on a host too.
#
set -euo pipefail

SRC_DIR="${SRC_DIR:-/src}"
WORK_DIR="${WORK_DIR:-/work}"
BUILD_DIR="${WORK_DIR}/build"
OUT_DIR="${WORK_DIR}/out"

CC="${CC:-clang}"
CXX="${CXX:-clang++}"

# fuzzer-no-link: instrument the libraries for coverage but don't pull in the
# libFuzzer main() (only the final harness link gets -fsanitize=fuzzer).
#
# -fno-sanitize=function: OpenJPEG (and GDCM) call through generic function
# pointers by design (opaque-handle C API). UBSan's function-pointer *type*
# check flags that idiom as a false positive that has nothing to do with memory
# safety, so we disable just that one check — matching how OSS-Fuzz fuzzes these
# projects. ASan + the rest of UBSan still catch real corruption.
SAN="address,undefined"
NOSAN="-fno-sanitize=function"
LIB_FLAGS="-g -O1 -fno-omit-frame-pointer -fsanitize=fuzzer-no-link,${SAN} ${NOSAN}"
BIN_FLAGS="-g -O1 -fno-omit-frame-pointer -fsanitize=fuzzer,${SAN} ${NOSAN}"

mkdir -p "${BUILD_DIR}" "${OUT_DIR}"

# Record pinned source SHAs for host builds too (the Dockerfile writes this at
# image-build time; direct SRC_DIR/WORK_DIR builds must generate it themselves so
# triage.sh and the disclosure report have real "version tested" provenance).
{
    for repo in openjpeg gdcm charls; do
        if [ -d "${SRC_DIR}/${repo}/.git" ]; then
            printf '%-9s %s %s\n' "${repo}" \
                "$(git -C "${SRC_DIR}/${repo}" describe --tags --always 2>/dev/null || echo '?')" \
                "$(git -C "${SRC_DIR}/${repo}" rev-parse HEAD 2>/dev/null || echo '?')"
        fi
    done
    # GDCM links its OWN bundled OpenJPEG (GDCM_USE_SYSTEM_OPENJPEG=OFF), NOT the
    # standalone /src/openjpeg tree above. A crash the gdcm target attributes to
    # OpenJPEG therefore reproduces on GDCM's vendored copy, whose revision is the
    # gdcm SHA — not necessarily the standalone OPENJPEG_TAG. Note this in reports.
    echo "note: gdcm target uses GDCM's bundled OpenJPEG (provenance = the gdcm SHA above)"
} > "${OUT_DIR}/versions.txt"
cat "${OUT_DIR}/versions.txt"

echo "==> Building OpenJPEG (static, instrumented)"
cmake -S "${SRC_DIR}/openjpeg" -B "${BUILD_DIR}/openjpeg" -G Ninja \
    -DCMAKE_BUILD_TYPE=Debug \
    -DBUILD_SHARED_LIBS=OFF \
    -DBUILD_CODEC=OFF \
    -DCMAKE_C_COMPILER="${CC}" \
    -DCMAKE_C_FLAGS="${LIB_FLAGS}"
cmake --build "${BUILD_DIR}/openjpeg" -j"$(nproc)"

OPJ_INC="${SRC_DIR}/openjpeg/src/lib/openjp2"
OPJ_GEN="${BUILD_DIR}/openjpeg/src/lib/openjp2"   # opj_config.h etc. land here
OPJ_LIB="$(find "${BUILD_DIR}/openjpeg" -name 'libopenjp2.a' | head -n1)"

echo "==> Linking harness_openjpeg"
"${CC}" ${BIN_FLAGS} \
    -I"${OPJ_INC}" -I"${OPJ_GEN}" \
    "${WORK_DIR}/harness_openjpeg.c" \
    "${OPJ_LIB}" \
    -o "${OUT_DIR}/fuzz_openjpeg"

echo "==> Building GDCM (static, instrumented, bundled OpenJPEG)"
# GDCM_USE_SYSTEM_OPENJPEG=OFF => test GDCM's own wrapper over its bundled codec.
cmake -S "${SRC_DIR}/gdcm" -B "${BUILD_DIR}/gdcm" -G Ninja \
    -DCMAKE_BUILD_TYPE=Debug \
    -DBUILD_SHARED_LIBS=OFF \
    -DGDCM_BUILD_SHARED_LIBS=OFF \
    -DGDCM_USE_SYSTEM_OPENJPEG=OFF \
    -DGDCM_BUILD_APPLICATIONS=OFF \
    -DGDCM_BUILD_TESTING=OFF \
    -DGDCM_BUILD_EXAMPLES=OFF \
    -DCMAKE_C_COMPILER="${CC}" \
    -DCMAKE_CXX_COMPILER="${CXX}" \
    -DCMAKE_C_FLAGS="${LIB_FLAGS}" \
    -DCMAKE_CXX_FLAGS="${LIB_FLAGS}"
cmake --build "${BUILD_DIR}/gdcm" -j"$(nproc)"

# Collect GDCM's public headers and the static libs it produced.
GDCM_INC_FLAGS=""
for d in \
    "${SRC_DIR}/gdcm/Source/Common" \
    "${SRC_DIR}/gdcm/Source/DataStructureAndEncodingDefinition" \
    "${SRC_DIR}/gdcm/Source/MediaStorageAndFileFormat" \
    "${BUILD_DIR}/gdcm/Source/Common" ; do
    [ -d "$d" ] && GDCM_INC_FLAGS="${GDCM_INC_FLAGS} -I${d}"
done

# Link every GDCM static archive we built (order-independent via --start-group).
mapfile -t GDCM_LIBS < <(find "${BUILD_DIR}/gdcm" -name 'libgdcm*.a')

echo "==> Linking harness_gdcm"
"${CXX}" ${BIN_FLAGS} \
    ${GDCM_INC_FLAGS} \
    "${WORK_DIR}/harness_gdcm.cxx" \
    -Wl,--start-group "${GDCM_LIBS[@]}" -Wl,--end-group \
    -o "${OUT_DIR}/fuzz_gdcm"

echo "==> Building CharLS (static, instrumented)  [SUSP-BIO-05: JPEG-LS]"
cmake -S "${SRC_DIR}/charls" -B "${BUILD_DIR}/charls" -G Ninja \
    -DCMAKE_BUILD_TYPE=Debug \
    -DBUILD_SHARED_LIBS=OFF \
    -DCHARLS_BUILD_TESTS=OFF \
    -DCHARLS_BUILD_SAMPLES=OFF \
    -DCHARLS_BUILD_FUZZ_TEST=OFF \
    -DCMAKE_C_COMPILER="${CC}" \
    -DCMAKE_CXX_COMPILER="${CXX}" \
    -DCMAKE_C_FLAGS="${LIB_FLAGS}" \
    -DCMAKE_CXX_FLAGS="${LIB_FLAGS}"
cmake --build "${BUILD_DIR}/charls" -j"$(nproc)"

CHARLS_LIB="$(find "${BUILD_DIR}/charls" -name 'libcharls.a' | head -n1)"

echo "==> Linking harness_charls"
"${CXX}" ${BIN_FLAGS} \
    -I"${SRC_DIR}/charls/include" \
    "${WORK_DIR}/harness_charls.cxx" \
    "${CHARLS_LIB}" \
    -o "${OUT_DIR}/fuzz_charls"

# ASan-ONLY CharLS variant, so the documented ASan-only deep run in RESULTS.md is
# reproducible. The default (address,undefined) build halts on CharLS's known
# signed-overflow UB (halt_on_error=1), which would stop workers before the
# memory-safety hunt; this variant drops UBSan so the hunt for real corruption
# runs to completion. run.sh / triage.sh expose it as the `charls_asan` target.
ASAN_ONLY_LIB_FLAGS="-g -O1 -fno-omit-frame-pointer -fsanitize=fuzzer-no-link,address"
ASAN_ONLY_BIN_FLAGS="-g -O1 -fno-omit-frame-pointer -fsanitize=fuzzer,address"
echo "==> Building CharLS (ASan-only variant)  [reproduces RESULTS.md ASan-only run]"
cmake -S "${SRC_DIR}/charls" -B "${BUILD_DIR}/charls_asan" -G Ninja \
    -DCMAKE_BUILD_TYPE=Debug \
    -DBUILD_SHARED_LIBS=OFF \
    -DCHARLS_BUILD_TESTS=OFF \
    -DCHARLS_BUILD_SAMPLES=OFF \
    -DCHARLS_BUILD_FUZZ_TEST=OFF \
    -DCMAKE_C_COMPILER="${CC}" \
    -DCMAKE_CXX_COMPILER="${CXX}" \
    -DCMAKE_C_FLAGS="${ASAN_ONLY_LIB_FLAGS}" \
    -DCMAKE_CXX_FLAGS="${ASAN_ONLY_LIB_FLAGS}"
cmake --build "${BUILD_DIR}/charls_asan" -j"$(nproc)"
echo "==> Linking harness_charls_asan"
"${CXX}" ${ASAN_ONLY_BIN_FLAGS} \
    -I"${SRC_DIR}/charls/include" \
    "${WORK_DIR}/harness_charls.cxx" \
    "$(find "${BUILD_DIR}/charls_asan" -name 'libcharls.a' | head -n1)" \
    -o "${OUT_DIR}/fuzz_charls_asan"

# Record which sanitizer set each CharLS binary carries, for report provenance.
{
    echo "charls-build fuzz_charls: fuzzer,address,undefined -fno-sanitize=function"
    echo "charls-build fuzz_charls_asan: fuzzer,address (ASan-only; reproduces RESULTS.md deep run)"
} >> "${OUT_DIR}/versions.txt"

echo "==> Seeding corpus from upstream test images (if present)"
mkdir -p "${WORK_DIR}/corpus"
find "${SRC_DIR}/openjpeg" -type f \( -name '*.j2k' -o -name '*.jp2' \) \
    -exec cp -n {} "${WORK_DIR}/corpus/" \; 2>/dev/null || true
find "${SRC_DIR}/gdcm" -type f -name '*.dcm' \
    -exec cp -n {} "${WORK_DIR}/corpus/" \; 2>/dev/null || true
find "${SRC_DIR}/charls" -type f -name '*.jls' \
    -exec cp -n {} "${WORK_DIR}/corpus/" \; 2>/dev/null || true

echo "==> Build complete. Binaries in ${OUT_DIR}:"
ls -l "${OUT_DIR}"/fuzz_* || true
echo "==> Pinned versions:"
cat "${OUT_DIR}/versions.txt" 2>/dev/null || echo "(versions.txt written by Docker build)"
