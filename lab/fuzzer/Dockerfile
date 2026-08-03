# Fuzzing host: all three surfaces' tooling in one image.
# Build context is ./fuzzer. Brought up by ../docker-compose.yml.
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv pipx \
      clang llvm lld \
      afl++ \
      build-essential cmake git \
      curl jq netcat-openbsd tcpdump \
      gdb \
    && rm -rf /var/lib/apt/lists/*

# Python fuzzing tooling (isolated venv).
RUN python3 -m venv /opt/fuzz && \
    /opt/fuzz/bin/pip install --no-cache-dir \
      schemathesis \
      boofuzz \
      hypothesis \
      requests
ENV PATH="/opt/fuzz/bin:${PATH}"

# libFuzzer ships with clang; AFL++ from apt. Verify at build:
RUN clang --version && afl-fuzz -h >/dev/null 2>&1 || true

# Campaign scripts live in the mounted ./campaigns volume at runtime.
WORKDIR /work
CMD ["bash"]
