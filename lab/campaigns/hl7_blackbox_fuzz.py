#!/usr/bin/env python3
"""Standalone black-box HL7 v2 / MLLP fuzzer (no external deps).

Sends mutated HL7 messages to a target MLLP listener and flags cases after which
the target stops responding (connection refused / reset / timeout) — the signal
of a crashed or hung parser. Every sent case is logged so a crash is reproducible.

Usage (point at your LAB instance, never production):
    python3 hl7_blackbox_fuzz.py --host chameleon.lab.internal --port 2575 \
        --iterations 500 --out /work/crashes

This is intentionally dependency-free so it runs anywhere Python 3 is available.
For deeper/stateful campaigns use the boofuzz version (hl7_boofuzz.py).
"""
import argparse
import os
import random
import socket
import time

SB, EB, CR = b"\x0b", b"\x1c", b"\x0d"  # MLLP framing

BASE = (
    "MSH|^~\\&|SENDING_APP|SENDING_FAC|RECV_APP|RECV_FAC|"
    "20260101000000||ADT^A01|MSG00001|P|2.5\r"
    "PID|1||PATID1234||DOE^JOHN||19700101|M\r"
)

# Mutation primitives typical of parser-breaking HL7 input.
def mutate(msg: str, rng: random.Random) -> str:
    strategies = [
        lambda m: m.replace("PATID1234", "A" * rng.choice([1024, 65535, 1 << 18])),  # oversized field
        lambda m: m.replace("|", "|" * rng.randint(50, 500), 1),                       # delimiter flood
        lambda m: m.replace("^~\\&", rng.choice(["", "^", "|||", "\x00\x00"])),        # broken encoding chars
        lambda m: m + "OBX|" + "|".join(["X" * 100] * rng.randint(5, 50)) + "\r",       # segment explosion
        lambda m: m.replace("2.5", rng.choice(["9.9", "", "2.5.1.9.9.9"])),            # bad version
        lambda m: m[: rng.randint(1, len(m))],                                          # truncation
        lambda m: m.replace("DOE^JOHN", "DOE^" + "\x00" * rng.randint(1, 40)),          # embedded nulls
        lambda m: m.replace("19700101", "9" * rng.choice([32, 256])),                   # numeric overflow-ish
    ]
    m = msg
    for _ in range(rng.randint(1, 3)):
        m = rng.choice(strategies)(m)
    return m


def frame(msg: str) -> bytes:
    return SB + msg.encode("latin-1", "replace") + EB + CR


def target_alive(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def send_case(host: str, port: int, payload: bytes, timeout: float = 3.0):
    with socket.create_connection((host, port), timeout=timeout) as s:
        s.sendall(payload)
        try:
            s.recv(4096)  # ACK/NAK if any
        except OSError:
            pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="chameleon.lab.internal")
    ap.add_argument("--port", type=int, default=2575)
    ap.add_argument("--iterations", type=int, default=500)
    ap.add_argument("--seed", type=int, default=1337)
    ap.add_argument("--out", default="./crashes")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    rng = random.Random(args.seed)
    log = open(os.path.join(args.out, "hl7_fuzz.log"), "w")

    if not target_alive(args.host, args.port):
        print(f"[!] Target {args.host}:{args.port} not reachable at start. Is the lab up?")
        return

    crashes = 0
    for i in range(args.iterations):
        payload = frame(mutate(BASE, rng))
        try:
            send_case(args.host, args.port, payload)
            status = "ok"
        except OSError as e:
            status = f"send-error({e})"

        # Liveness probe: if the target no longer accepts connections, the last
        # case likely crashed/hung it.
        if not target_alive(args.host, args.port):
            crashes += 1
            crash_path = os.path.join(args.out, f"crash_{i:05d}.hl7")
            with open(crash_path, "wb") as f:
                f.write(payload)
            msg = f"[CRASH] iter={i} target down after case -> saved {crash_path}"
            print(msg); log.write(msg + "\n"); log.flush()
            # wait for a possible auto-restart before continuing
            for _ in range(10):
                if target_alive(args.host, args.port):
                    break
                time.sleep(1)
        else:
            log.write(f"iter={i} {status}\n")

    summary = f"[*] Done. {args.iterations} cases, {crashes} crash-signals. See {args.out}"
    print(summary); log.write(summary + "\n"); log.close()


if __name__ == "__main__":
    main()
