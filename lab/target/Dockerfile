# PLACEHOLDER target image.
#
# This does NOT contain Chameleon — Elad's software is yours to supply from the
# authorized copy. Replace the body below with the real build/install steps, or
# point docker-compose.yml at a provided image instead of building this.
#
# The stub just documents the expected listeners so `docker compose up` succeeds
# and the fuzzer's network wiring can be tested before the real target is in.

FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# --- REPLACE FROM HERE with the real Chameleon install ------------------------
# e.g.
#   COPY ./chameleon-installer /opt/chameleon
#   RUN /opt/chameleon/install.sh
#   CMD ["/opt/chameleon/bin/start"]
#
# Until then, a stub that just holds the HL7 port open so wiring can be verified:
CMD ["sh", "-c", "echo 'PLACEHOLDER target — replace with authorized Chameleon copy'; \
     while true; do nc -l -p 2575 -q 1 >/dev/null 2>&1 || sleep 1; done"]
# --- REPLACE TO HERE ----------------------------------------------------------
