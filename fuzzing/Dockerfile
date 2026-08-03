# Fuzzing environment for SUSP-BIO-04 (JPEG2000 decode path: OpenJPEG + GDCM)
#
# Isolated, reproducible build. Everything here compiles open-source code you
# control and runs locally — no live system is touched. See README.md.
#
# Build:  docker build -t biofuzz fuzzing/
# Run:    docker run --rm -it -v "$PWD/fuzzing/out:/work/out" biofuzz
#
# Pin the exact upstream tags here so results are reproducible and so the
# "version tested" field of any disclosure report is unambiguous. Bump these
# to the latest releases before a real run and record the resolved SHAs
# (build.sh prints them into out/versions.txt).

FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Toolchain: clang/llvm provide libFuzzer + the sanitizer runtimes and
# llvm-symbolizer (needed for readable ASan/UBSan stacks during triage).
RUN apt-get update && apt-get install -y --no-install-recommends \
        clang \
        llvm \
        libclang-rt-18-dev \
        cmake \
        ninja-build \
        make \
        git \
        ca-certificates \
        python3 \
    && rm -rf /var/lib/apt/lists/*
# libclang-rt-18-dev provides the compiler-rt static libs (libclang_rt.asan-*.a)
# that -fsanitize=address,fuzzer link against; `clang` alone does not ship them
# on Ubuntu 24.04. If you change the base image's clang major version, match the
# libclang-rt-<N>-dev version to it.

# --- Pinned upstream versions -------------------------------------------------
# Change these to the current release tags before a hunt, then rebuild.
ARG OPENJPEG_TAG=v2.5.3
ARG GDCM_TAG=v3.0.24
ARG CHARLS_TAG=2.4.2

WORKDIR /src
RUN git clone --depth 1 --branch ${OPENJPEG_TAG} https://github.com/uclouvain/openjpeg.git openjpeg \
 && git clone --depth 1 --branch ${GDCM_TAG}     https://github.com/malaterre/GDCM.git gdcm \
 && git clone --depth 1 --branch ${CHARLS_TAG}   https://github.com/team-charls/charls.git charls

# Record the exact resolved commit SHAs — needed to prove a crash is on the
# pinned-latest code (i.e. not an already-fixed bug) in the disclosure report.
RUN mkdir -p /work/out \
 && echo "openjpeg ${OPENJPEG_TAG} $(git -C /src/openjpeg rev-parse HEAD)" >  /work/out/versions.txt \
 && echo "gdcm     ${GDCM_TAG} $(git -C /src/gdcm rev-parse HEAD)"          >> /work/out/versions.txt \
 && echo "charls   ${CHARLS_TAG} $(git -C /src/charls rev-parse HEAD)"      >> /work/out/versions.txt

WORKDIR /work
COPY build.sh run.sh triage.sh /work/
COPY harness_openjpeg.c harness_gdcm.cxx harness_charls.cxx /work/
COPY corpus /work/corpus
RUN chmod +x /work/*.sh

# Sanitizer defaults for every run inside the container.
ENV ASAN_OPTIONS=abort_on_error=1:allocator_may_return_null=1:detect_leaks=0
ENV UBSAN_OPTIONS=print_stacktrace=1:halt_on_error=1

# Build both instrumented fuzz binaries at image-build time so `docker run`
# drops you straight into a ready-to-fuzz shell.
RUN /work/build.sh

CMD ["/bin/bash"]
