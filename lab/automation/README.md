# Fuzzing Orchestrator (continuous, all surfaces)

Automates the black-box fuzzing loop against an **isolated lab copy** of
Chameleon: rotates through every enabled surface that has its inputs
(HL7/MLLP · HTTP API · file/binary parser), keeps the target alive across
crashes, and continuously triages + reports.

```
config.yml ──▶ fuzz_orchestrator.py ──▶ [hl7] [api] [parser] rounds, looping
                     │                        │
                     │                 target_monitor.py  (liveness + auto-restart)
                     ▼
              triage.py ──▶ findings.json ──▶ report.py ──▶ out/report.md
```

## Safety (enforced in code, not just docs)

`fuzz_orchestrator.py` runs a **preflight** and refuses to start unless:
1. `safety.lab_confirmed: true` (you attest the target is a non-production copy),
2. `target_host` is private/loopback **or** in `safety.allow_hosts`, and
3. `target_host` matches none of `safety.deny_host_markers` (prod/hospital markers).

Pointing it at production is therefore a blocked state by construction. This tool
is for a lab copy only — never the live clinical system.

## Use

1. Edit `config.yml`: set `target_host`, ports, and per-surface inputs
   (`api.spec`, `parser.target_bin` + `seed_corpus`). Set `safety.lab_confirmed: true`
   once you've confirmed the target is a lab copy.
2. Bring up the lab (`../docker-compose.yml`), then:
   ```bash
   make fuzz        # continuous loop
   make stop        # signal it to stop cleanly (from another shell)
   ```
3. Read `out/report.md`; hand `out/crashes/` + `out/findings.json` back for triage.

Surfaces with missing inputs are **skipped with a logged notice**, so a run works
even if only HL7 is wired up.

## Validate the tooling first (no real target)

```bash
make selftest          # runs against the crash-on-oversized-field mock
make selftest-safety   # confirms a production-looking host is REFUSED
```

`make selftest` should: capture crash inputs, auto-restart the mock after each
simulated crash, dedup to the single `hl7:oversized-field` root cause with a
minimized reproducer, and write `out/report.md`.

## Crash → disclosure handoff

Crash counts in the report are **lab findings requiring vendor triage, not
confirmed CVEs**. For a genuine bug: reproduce on a fresh snapshot, classify with
a debugger/sanitizer, then draft the coordinated-disclosure report to Elad
Systems (vendor first → CVE → publish), same process as the C-1 advisory in
`docs/`.
