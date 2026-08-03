#!/usr/bin/env python3
"""Target liveness monitor + auto-restart for the fuzzing lab.

Probes the configured TCP port(s); when the target stops accepting connections
(a crashed/hung parser), it runs the configured restart command and waits for
the target to come back. Runs as a background thread inside the orchestrator, so
every surface benefits from crash recovery without each fuzzer implementing it.
"""
import shlex
import socket
import subprocess
import threading
import time


class TargetMonitor:
    def __init__(self, host, ports, restart_cmd, interval=2.0, logger=print):
        self.host = host
        self.ports = [int(p) for p in ports if p]
        self.restart_cmd = restart_cmd
        self.interval = float(interval)
        self.log = logger
        self.restarts = 0
        self._stop = threading.Event()
        self._thread = None

    def alive(self, timeout=3.0):
        """True if ANY configured port accepts a connection."""
        for port in self.ports:
            try:
                with socket.create_connection((self.host, port), timeout=timeout):
                    return True
            except OSError:
                continue
        return False

    def restart(self):
        if not self.restart_cmd:
            self.log("[monitor] no restart_cmd configured; cannot restart target")
            return
        self.log(f"[monitor] restarting target: {self.restart_cmd}")
        try:
            subprocess.Popen(shlex.split(self.restart_cmd),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.restarts += 1
        except Exception as e:  # noqa: BLE001 - report and continue
            self.log(f"[monitor] restart failed: {e}")

    def ensure_up(self, wait=30.0):
        """Block until the target is up (restarting once if needed)."""
        if self.alive():
            return True
        self.restart()
        deadline = time.time() + wait
        while time.time() < deadline:
            if self.alive():
                self.log("[monitor] target back up")
                return True
            time.sleep(1)
        self.log("[monitor] target still down after restart window")
        return False

    def _loop(self):
        while not self._stop.is_set():
            if not self.alive():
                self.log("[monitor] target DOWN — recovering")
                self.ensure_up()
            self._stop.wait(self.interval)

    def start(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, action="append", required=True)
    ap.add_argument("--restart-cmd", default="")
    args = ap.parse_args()
    m = TargetMonitor(args.host, args.port, args.restart_cmd)
    print("alive:", m.alive())
