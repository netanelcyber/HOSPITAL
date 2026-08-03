#!/usr/bin/env python3
"""Continuous fuzzing orchestrator for an AUTHORIZED Chameleon lab copy.

Rotates through every enabled surface that has its required inputs (HL7 / HTTP
API / file-or-binary parser), running one bounded round each, while a background
monitor keeps the target alive across crashes. After every round it triages the
captured crashes and regenerates the report. Loops until SIGINT or a stop-file.

SAFETY: refuses to start unless the target is attested as a lab copy and its host
is private/allowlisted and not production-marked. This makes pointing the tool at
production a blocked state by construction — see _safety_preflight().
"""
import ipaddress
import os
import signal
import socket
import subprocess
import sys
import time

import yaml

import triage as triage_mod
import report as report_mod
from target_monitor import TargetMonitor

HERE = os.path.dirname(os.path.abspath(__file__))
STOP_FILE = os.path.join(HERE, ".stop")


def log(msg):
    print(f"[orchestrator] {msg}", flush=True)


def load_config(path):
    with open(path) as fh:
        return yaml.safe_load(fh)


def _host_is_private(host):
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = info[4][0]
        try:
            addr = ipaddress.ip_address(ip)
            if not (addr.is_private or addr.is_loopback or addr.is_link_local):
                return False
        except ValueError:
            return False
    return True


def _safety_preflight(cfg):
    """Hard-refuse unless the target is a confirmed, private/allowlisted lab host."""
    safety = cfg.get("safety", {})
    host = str(cfg.get("target_host", "")).strip()
    errors = []

    if not safety.get("lab_confirmed", False):
        errors.append("safety.lab_confirmed is not true — you must attest the "
                      "target is a NON-PRODUCTION lab copy.")

    markers = [m.lower() for m in safety.get("deny_host_markers", [])]
    if any(m in host.lower() for m in markers):
        errors.append(f"target_host '{host}' matches a production marker "
                      f"({', '.join(markers)}).")

    allow = set(safety.get("allow_hosts", []))
    if host not in allow and not _host_is_private(host):
        errors.append(f"target_host '{host}' is neither in allow_hosts nor a "
                      f"private/loopback address. Refusing (possible production).")

    if errors:
        log("SAFETY PREFLIGHT FAILED — not starting:")
        for e in errors:
            log(f"  - {e}")
        log("This tool only runs against an isolated lab copy of Chameleon.")
        sys.exit(2)
    log(f"safety preflight OK — target '{host}' accepted as lab copy")


def _enabled_ports(cfg):
    ports = []
    s = cfg.get("surfaces", {})
    if s.get("hl7", {}).get("enabled"):
        ports.append(s["hl7"].get("port", 2575))
    return ports or [cfg.get("surfaces", {}).get("hl7", {}).get("port", 2575)]


# ---- surface runners: each returns True if it actually ran a round ----------

def run_hl7(cfg, out_dir):
    s = cfg["surfaces"]["hl7"]
    if not s.get("enabled"):
        return False
    crashes = os.path.join(out_dir, "crashes")
    cmd = [sys.executable, os.path.join(HERE, "..", "campaigns", "hl7_blackbox_fuzz.py"),
           "--host", cfg["target_host"], "--port", str(s.get("port", 2575)),
           "--iterations", str(s.get("iterations_per_round", 300)),
           "--out", crashes]
    log(f"HL7 round: {s.get('iterations_per_round', 300)} cases -> {crashes}")
    subprocess.run(cmd, cwd=HERE)
    return True


def run_api(cfg, out_dir):
    s = cfg["surfaces"].get("api", {})
    if not s.get("enabled"):
        return False
    spec = s.get("spec", "").strip()
    if not spec:
        log("API surface enabled but no spec configured — SKIPPING")
        return False
    env = dict(os.environ, TARGET=s.get("base_url", cfg["target_host"]),
               SPEC=spec, MAX=str(s.get("max_examples", 500)))
    log(f"API round via schemathesis against spec {spec}")
    subprocess.run(["bash", os.path.join(HERE, "..", "campaigns", "run_api.sh")],
                   cwd=HERE, env=env)
    return True


def run_parser(cfg, out_dir):
    s = cfg["surfaces"].get("parser", {})
    if not s.get("enabled"):
        return False
    target_bin = s.get("target_bin", "").strip()
    corpus = s.get("seed_corpus", "").strip()
    if not target_bin or not corpus:
        log("Parser surface enabled but target_bin/seed_corpus not set — SKIPPING")
        return False
    crashes = os.path.join(out_dir, "crashes", "parser")
    os.makedirs(crashes, exist_ok=True)
    # Black-box binary fuzzing (no source): AFL++ QEMU mode.
    cmd = ["afl-fuzz", "-Q", "-i", corpus, "-o", crashes,
           "-V", str(s.get("afl_timeout_sec", 600)), "--", target_bin, "@@"]
    log(f"Parser round: AFL++ QEMU over {target_bin}")
    try:
        subprocess.run(cmd, cwd=HERE)
    except FileNotFoundError:
        log("afl-fuzz not found — install AFL++ in the fuzzer image. SKIPPING")
        return False
    return True


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(HERE, "config.yml"))
    ap.add_argument("--max-rounds", type=int, default=0,
                    help="stop after N rounds (0 = until stop-file/SIGINT)")
    args = ap.parse_args()

    cfg = load_config(args.config)
    _safety_preflight(cfg)

    out_dir = os.path.abspath(os.path.join(HERE, cfg.get("out_dir", "./out")))
    os.makedirs(out_dir, exist_ok=True)
    if os.path.exists(STOP_FILE):
        os.remove(STOP_FILE)

    monitor = TargetMonitor(cfg["target_host"], _enabled_ports(cfg),
                            cfg.get("restart_cmd", ""),
                            cfg.get("monitor_interval_sec", 2), logger=log).start()

    stop = {"flag": False}
    signal.signal(signal.SIGINT, lambda *_: stop.update(flag=True))
    signal.signal(signal.SIGTERM, lambda *_: stop.update(flag=True))

    surfaces = [("hl7", run_hl7), ("api", run_api), ("parser", run_parser)]
    ran_surfaces, rounds = set(), 0
    log("starting continuous loop (Ctrl-C or `make stop` to end)")
    monitor.ensure_up()

    try:
        while not stop["flag"] and not os.path.exists(STOP_FILE):
            for name, fn in surfaces:
                if stop["flag"] or os.path.exists(STOP_FILE):
                    break
                monitor.ensure_up()
                if fn(cfg, out_dir):
                    ran_surfaces.add(name)
                    rounds += 1
                    # triage + report after each round
                    res = triage_mod.triage_dir(os.path.join(out_dir, "crashes"), out_dir)
                    report_mod.render(
                        os.path.join(out_dir, "findings.json"),
                        os.path.join(out_dir, "report.md"),
                        meta={"target": cfg["target_host"], "rounds": rounds,
                              "surfaces": sorted(ran_surfaces),
                              "restarts": monitor.restarts})
                    log(f"round {rounds} done — {res['unique_buckets']} unique "
                        f"crash buckets; report -> {out_dir}/report.md")
                if args.max_rounds and rounds >= args.max_rounds:
                    stop["flag"] = True
                    break
            time.sleep(1)
    finally:
        monitor.stop()
        log(f"stopped after {rounds} rounds. Report: {out_dir}/report.md")


if __name__ == "__main__":
    main()
