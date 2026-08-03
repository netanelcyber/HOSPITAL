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
