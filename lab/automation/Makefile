# Chameleon fuzzing orchestrator entrypoints.
# All targets operate on an ISOLATED LAB COPY only (enforced by the safety
# preflight in fuzz_orchestrator.py).

PY ?= python3

.PHONY: fuzz selftest selftest-safety stop clean

# Continuous fuzzing against the lab instance configured in config.yml.
fuzz:
	$(PY) fuzz_orchestrator.py --config config.yml

# End-to-end self-validation against the mock (no real target). Should capture
# crashes, auto-restart the mock, triage to one root cause, and write report.md.
selftest:
	$(PY) fuzz_orchestrator.py --config selftest.config.yml --max-rounds 3

# Negative test: production-looking target must be REFUSED (expect exit code 2).
selftest-safety:
	@$(PY) fuzz_orchestrator.py --config selftest.prod.config.yml; \
	  code=$$?; \
	  if [ $$code -eq 2 ]; then echo "PASS: production target refused"; else \
	  echo "FAIL: expected refusal (exit 2), got $$code"; exit 1; fi

# Signal a running continuous loop to stop cleanly.
stop:
	touch .stop

clean:
	rm -rf out .stop
