# Chameleon (Elad Systems) — Fuzzing Lab Plan & Harness Scaffolding

**Prepared for:** Elad
**Date:** 2026-08-02
**Target:** Elad Systems "Chameleon" (קמיליון) — **authorized copy only**
**Access available:** staging/test instance · source code · binaries/installer
**Surfaces in scope:** Web app / HTTP API · healthcare protocols (HL7/FHIR/DICOM) ·
desktop/thick client + file formats

> **Rule zero — where this runs.** Everything below targets an **isolated lab
> instance** of Chameleon that you stand up from the authorized copy. Not the
> production system, and not anything reachable from the hospital network. Fuzzing
> is designed to crash things; a clinical production system is never an acceptable
> place to do it, regardless of authorization. Keep the lab air-gapped or on an
> isolated VLAN, seed it only with **synthetic/de-identified data** (never real
> PHI), and snapshot the VMs so you can roll back after crashes.

---

## 0. Lab prerequisites (do these first)

1. **Isolated environment** — dedicated VMs / network segment with no route to
   production or to any live medical device. Host the DB and app tiers inside it.
2. **Synthetic data only** — generate fake patients/records. If a DB dump is
   needed for realism, it must be **de-identified** before it enters the lab.
3. **Snapshots** — base snapshot of every VM before each campaign, so a crash or
   corruption is a `revert`, not an incident.
4. **Monitoring** — enable core dumps / crash logging on the app and DB tiers;
   install the debuggers named per-surface below so crashes are actually captured.
5. **Written scope on file** — keep your authorization / RoE document with the
   lab notes, listing exactly which components and versions are in scope.

---

## 1. Web app / HTTP API surface

### Tooling
- **Schemathesis** — if Chameleon exposes an OpenAPI/Swagger spec (or a FHIR
  CapabilityStatement), this is the fastest high-coverage property-based fuzzer.
- **RESTler** (Microsoft) — stateful API fuzzing; infers request sequences from a
  spec. Best for finding order-dependent bugs (auth-then-action).
- **Burp Suite Intruder / Pro** — targeted parameter fuzzing, auth handling,
  session management; good for manual follow-up on Schemathesis hits.
- **ffuf / feroxbuster** — content/endpoint discovery to map the surface first.

### Approach
1. **Map** the surface: crawl the app authenticated + unauthenticated; pull any
   OpenAPI/WSDL/GraphQL schema from the source tree.
2. **Property fuzz** every endpoint with Schemathesis (examples below), watching
   for 500s, timeouts, reflected input, auth bypasses.
3. **Stateful fuzz** login→action sequences with RESTler to catch broken access
   control and mass-assignment (the exact class that hit open-source Camaleon).
4. **Targeted** file-upload endpoints (medical document/image import) — these are
   the highest-value web sinks; fuzz content-type, filename (path traversal),
   and body.

### Starter commands
```bash
# Property-based API fuzzing from an OpenAPI spec against the LAB host
schemathesis run \
  --checks all \
  --hypothesis-max-examples 500 \
  --header "Authorization: Bearer $LAB_TOKEN" \
  http://chameleon.lab.internal/openapi.json

# Endpoint discovery
ffuf -w /usr/share/seclists/Discovery/Web-Content/raft-large-words.txt \
     -u http://chameleon.lab.internal/FUZZ -mc all -fc 404
```

Watch for: unhandled 500s, stack traces in responses, response-time cliffs
(ReDoS/algorithmic), auth checks that differ by verb or path casing, and any
input reflected unescaped (XSS) — the same sink families documented in the
open-source Camaleon audit are a useful checklist here.

---

## 2. Healthcare-protocol surface (HL7 v2 / FHIR / DICOM)

This is the surface unique to a hospital system and the most valuable to fuzz,
because these parsers historically pre-date modern input hardening.

### HL7 v2 (MLLP)
- **boofuzz** — Python fuzzing framework; drive the MLLP socket with mutated
  segments. Skeleton harness in `fuzz/hl7_boofuzz.py` (scaffold below).
- Fuzz: segment field counts, delimiter injection (`|^~\&`), oversized fields,
  malformed MSH, encoding, repetition markers, embedded binary.

### FHIR
- **Schemathesis** against the FHIR REST API + CapabilityStatement.
- Fuzz: malformed JSON/XML resources, deeply-nested/recursive structures
  (billion-laughs / stack exhaustion), invalid references, huge `Bundle`s,
  content-type confusion (XML vs JSON), `_search` parameter injection.

### DICOM
- **dicom-fuzzer** or a **boofuzz** DIMSE harness against the DICOM SCP port.
- Fuzz: malformed DICOM file meta / data elements, bad VR/length fields,
  oversized pixel data, association-negotiation PDUs.

### HL7 boofuzz scaffold (`fuzz/hl7_boofuzz.py`)
```python
# Fuzz an HL7 v2 MLLP listener on the LAB instance.
# MLLP frame = \x0b <HL7 message> \x1c \x0d
from boofuzz import Session, Target, SocketConnection, s_initialize, s_static, s_string, s_delim

HOST, PORT = "chameleon.lab.internal", 2575  # set to your lab MLLP port

def define_adt_a01():
    s_initialize("ADT_A01")
    s_static("\x0b")                                  # MLLP start block
    s_static("MSH")
    s_delim("|"); s_string("^~\\&")                   # encoding chars (fuzzed)
    s_delim("|"); s_string("SENDING_APP")
    s_delim("|"); s_string("SENDING_FAC")
    s_delim("|"); s_string("RECEIVING_APP")
    s_delim("|"); s_string("MSG00001")                # more fields...
    s_static("\r")
    s_static("PID")
    s_delim("|"); s_string("1")
    s_delim("|"); s_string("PATID1234")               # patient id (fuzzed)
    s_static("\x1c\x0d")                              # MLLP end block + CR

if __name__ == "__main__":
    define_adt_a01()
    session = Session(target=Target(connection=SocketConnection(HOST, PORT, proto="tcp")))
    session.connect(s_get("ADT_A01"))
    session.fuzz()
```
Point a monitor at the listener process (auto-restart + core dump on crash) so
boofuzz records which case killed it.

---

## 3. Desktop / thick-client + file-format surface

### With source (coverage-guided — the strongest method)
- **AFL++** (C/C++) or **libFuzzer** — write a harness that feeds one fuzzed
  input into the parser function and build it with sanitizers
  (`-fsanitize=address,undefined`). Coverage feedback finds deep bugs fast.
- Target the routines that parse **files/messages the client imports**: report
  formats, config files, exported records, image/document formats.

### libFuzzer harness template (`fuzz/parse_fuzzer.cc`)
```cpp
// Build: clang++ -g -O1 -fsanitize=address,undefined,fuzzer parse_fuzzer.cc \
//        chameleon_parser.o -o parse_fuzzer
// Run:   ./parse_fuzzer -max_len=65536 corpus/
#include <cstdint>
#include <cstddef>
extern "C" int chameleon_parse(const uint8_t* data, size_t size); // the target routine

extern "C" int LLVMFuzzerTestOneInput(const uint8_t* data, size_t size) {
    chameleon_parse(data, size);   // ASAN/UBSAN report memory + UB bugs
    return 0;
}
```

### Binary only (no source)
- **WinAFL** (`-fuzz_iterations`, DynamoRIO instrumentation) for Windows
  client parsers; pick the target function offset with the client's own
  file-open path.
- Seed a **corpus** from real (synthetic) sample files the client accepts, then
  minimize it (`afl-cmin`) before the campaign.

### Client↔server protocol
- Capture the thick client's traffic in the lab, model the protocol, and fuzz it
  with **boofuzz** the same way as HL7 above.

---

## 4. Crash triage & handling

1. **Reproduce** each crash from the saved test case against a fresh snapshot.
2. **Classify** with the sanitizer/debugger output: memory-safety (ASAN),
   assertion/DoS, logic. Note exploitability signal (write vs read, control of
   PC/registers).
3. **Minimize** the input (`afl-tmin`, `libFuzzer -minimize_crash`).
4. **Do not test findings against production.** A lab crash is the deliverable;
   confirmation stays in the lab.
5. **Report to Elad Systems** through the authorized channel, with the minimized
   repro and affected version. If it warrants a CVE, follow the coordinated-
   disclosure steps in the C-1 advisory draft (vendor first → CVE → publish).

---

## 5. Suggested campaign order

1. **Source-guided file/parser fuzzing** (§3) — highest signal, fully offline,
   safest. Start here while the instance is being stood up.
2. **HL7/DICOM protocol fuzzing** (§2) against the lab instance — unique,
   high-value surface.
3. **API property + stateful fuzzing** (§1) — broad coverage, catches the
   access-control/mass-assignment classes.
4. **Thick-client protocol fuzzing** (§3) — last, once the protocol is modeled.

---

## What I need from you to start building real harnesses

- Which **parsers / file formats** the client and server accept (from the source
  tree or docs) — so §3 harnesses target real entry points.
- Whether an **OpenAPI / WSDL / FHIR CapabilityStatement** exists in the source —
  unlocks §1 immediately.
- The **HL7/DICOM listener ports** and message types the lab instance supports.
- Language/build system of the components (for §3 sanitizer builds).

Share any of those (source snippets, a spec file, a sample message/file) and I'll
turn the scaffolds above into runnable, target-specific harnesses.
