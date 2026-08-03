# Chameleon Two-Host Fuzzing Lab

Infrastructure-as-code for the fuzzing setup you asked for:

```
  ┌─────────────────────┐        internal-only         ┌──────────────────────┐
  │  host 2: fuzzer     │  ─────  labnet (no net)  ───▶ │  host 1: target      │
  │  schemathesis/afl++ │        sends fuzzing          │  Chameleon copy      │
  │  boofuzz/libFuzzer  │                               │  chameleon.lab.int   │
  └─────────────────────┘                               └──────────────────────┘
```

**This scaffolding contains no Chameleon.** Elad's software is yours to supply
from the authorized copy — you drop it into `target/`. Everything else (the
fuzzing host, the isolated network, the campaigns) is ready.

## ⚠️ Ground rules (baked into the config)

- The `labnet` network is `internal: true` — **no internet, no route to
  production or any hospital system.** This lab is for a **non-production copy
  only.**
- Seed campaigns with **synthetic / de-identified data — never real PHI.**
- `restart: "no"` on the target so a crash **stays down** and the fuzzer records
  it. Snapshot/rebuild between runs.

## Bring it up

```bash
cd lab
docker compose up -d          # builds fuzzer + (placeholder) target
docker compose exec fuzzer bash
```

Until you add the real target, `target/` is a stub that just holds the HL7 port
open so you can verify the wiring:

```bash
# from inside the fuzzer container:
nc -vz chameleon.lab.internal 2575     # should connect to the stub
```

## Add the real target

Edit `target/Dockerfile` (replace the marked block with the real install), or
point `docker-compose.yml`'s `target.build` at `image: your-registry/chameleon:lab`.
Set the real listener ports in the `expose:` list.

## Run a campaign (inside the fuzzer container)

| Surface | Command | Needs |
|---|---|---|
| HTTP API | `campaigns/run_api.sh` | an OpenAPI spec at `campaigns/openapi.json` (or a URL) |
| HL7 v2 MLLP | `python3 campaigns/hl7_boofuzz.py` | target HL7 port |
| File/msg parser | build & run `campaigns/parser_libfuzzer.cc` | the parser routine + a seed corpus |

Crashes land in `crashes/` (mounted to your host).

## The triage loop (Option B)

1. Run a campaign in your lab.
2. Copy back the contents of `crashes/` — the **input** that crashed it, the
   **stack trace / sanitizer output**, and the **component + version**.
3. I reproduce, classify, minimize, and assess severity.
4. If it's a real vulnerability, I draft the coordinated-disclosure report to
   Elad Systems (vendor first → CVE → publish), same process as the C-1 advisory.

Nothing gets tested against production, and no finding is claimed without a
reproducible crash.
