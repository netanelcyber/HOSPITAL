# Engagement Summary — "Elad Chameleon Vulns"

**Date:** 2026-08-02 / 03
**Branch:** `claude/elad-chameleon-vulns-542ckv`
**Prepared for:** Elad

This is the entry point to everything produced in this engagement. Read the
**scope note** first — it determines which deliverables are relevant.

---

## ⚠️ Scope note (the single most important fact)

Two different products share the name "Chameleon":

- **Open-source Camaleon CMS** — the Ruby gem `camaleon_cms`. **All the CVE
  research, the source audit, and the confirmed C-1 finding below are about
  THIS.**
- **Elad Systems' proprietary "Chameleon" (קמיליון)** — a closed-source Israeli
  product, and the **actual intended target**. It shares only the name. **No
  first-party analysis of it was possible** — its code/instance were never
  available in this session.

Full detail: [`00-IMPORTANT-scope-correction.md`](./00-IMPORTANT-scope-correction.md).

---

## What was delivered

### A. CVE research — open-source Camaleon CMS (complete)
The full public vulnerability record, 2021–2026 (13 CVEs/advisories), with the
cloud-migration angle and a detection/response playbook.
- [`chameleon-cve-report.md`](./chameleon-cve-report.md) + addenda
  [1](./chameleon-cve-report-addendum.md) ·
  [2](./chameleon-cve-report-addendum-2.md) ·
  [3](./chameleon-cve-report-addendum-3.md)
- [`camaleon-detection-response-playbook.md`](./camaleon-detection-response-playbook.md)
- Key correction found: **CVE-2026-66748 affects 2.9.1** — the version first
  believed safe. Safe target is now a release **above 2.9.1**.

### B. Source audit — Camaleon CMS 2.9.2 (complete)
White-box review of current code. Every known-CVE class is fixed; the SSRF
surface is hardened down to DNS-rebinding and redirect bypasses.
- [`camaleon-2.9.2-source-audit.md`](./camaleon-2.9.2-source-audit.md)
- [`camaleon-2.9.2-candidate-findings.md`](./camaleon-2.9.2-candidate-findings.md)

### C. Confirmed finding — C-1 Open Redirect (CWE-601)
Found by source review, **validated end-to-end in a local sandbox** (Ruby 3.3.6
+ pinned Rails 8.1.3.1): `safe_redirect_url` and Rails' `redirect_to` share a
`nil`-host blind spot; `https:/evil.com` reaches the victim off-site. Low-to-
moderate severity. **Disclosure-ready.**
- [`camaleon-2.9.2-C1-open-redirect-advisory.md`](./camaleon-2.9.2-C1-open-redirect-advisory.md)
- **This is the one real, reportable result — against open-source Camaleon CMS.**

### D. Fuzzing lab + automation (built, validated against a mock)
For the intended target (Elad's Chameleon), a complete black-box fuzzing rig to
run against an **authorized lab copy** — never production.
- Plan: [`chameleon-fuzzing-plan.md`](./chameleon-fuzzing-plan.md)
- Two-host lab: [`../lab/`](../lab/) (docker-compose, fuzzer + target images,
  HL7/API/parser campaigns, self-test mock)
- Continuous orchestrator: [`../lab/automation/`](../lab/automation/) — rotates
  all surfaces, monitors/restarts the target, triages + reports; **code-enforced
  safety preflight refuses any non-lab/production target.**
- Validated: black-box HL7 fuzzer proven (19/120 crashes → dedup → minimized
  repro); orchestrator triage/report/skip/safety all tested.

---

## Honest status of the actual goal

**No vulnerability was found in Elad Systems' Chameleon**, because its source and
its instances were never available here. Nothing was tested against the live
hospital system, and no finding about Elad's product was fabricated.

What exists is: (1) one genuine, confirmed low-severity bug in the **open-source**
CMS of the same name, ready for coordinated disclosure to its maintainer, and
(2) a ready-to-run, safety-gated fuzzing pipeline for the **real** target that
only produces results when *you* run it against an authorized lab copy.

## To get real results on the intended target

1. Stand up an **authorized copy** of Elad's Chameleon in an isolated lab.
2. Point `lab/automation/config.yml` at it, set `safety.lab_confirmed: true`,
   `make fuzz`.
3. Return `out/crashes/` + `out/findings.json` → triage + coordinated disclosure
   to Elad Systems.

## Boundary that held throughout

No active testing of the live production system at Ichilov / Tel Aviv Sourasky on
an authorization that could not be verified here. An authorized lab copy is fully
in scope; the live clinical system is not.
