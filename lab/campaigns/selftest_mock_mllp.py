#!/usr/bin/env python3
"""Mock MLLP listener with a DELIBERATE parser bug, to validate the fuzzer.
Simulates a Chameleon-like HL7 endpoint that crashes when a field exceeds a
buffer (a classic parser flaw). NOT Chameleon — a stand-in so we can prove the
black-box fuzzer detects and records crashes before pointing it at a real lab.
"""
import socket, sys, os

HOST, PORT = "127.0.0.1", 2575
BUG_THRESHOLD = 60000  # "buffer" size the mock parser mishandles

def handle(data: bytes):
    # naive "parser": split fields, mishandle an oversized one -> crash the process
    body = data.strip(b"\x0b\x1c\x0d")
    for field in body.split(b"|"):
        if len(field) > BUG_THRESHOLD:
            # simulate memory-corruption crash: terminate the server process
            os._exit(139)  # 128+SIGSEGV, mimics a segfault
    return b"\x0bMSH|^~\\&|ACK\x1c\x0d"

def main():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, PORT)); s.listen(5)
    sys.stderr.write(f"mock MLLP up on {HOST}:{PORT} (bug threshold {BUG_THRESHOLD})\n")
    sys.stderr.flush()
    while True:
        conn, _ = s.accept()
        with conn:
            data = conn.recv(1 << 20)
            if data:
                try:
                    conn.sendall(handle(data))
                except OSError:
                    pass

if __name__ == "__main__":
    main()
