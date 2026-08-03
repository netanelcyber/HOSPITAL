#!/usr/bin/env python3
"""HL7 v2 (MLLP) fuzzing campaign against the lab target.

Run from inside the fuzzer container:
    python3 /work/campaigns/hl7_boofuzz.py

Adjust HOST/PORT and the message model to match your Chameleon lab instance.
Crashes/anomalies are recorded by boofuzz in ./crashes (mounted volume).
MLLP frame = \\x0b <HL7 message> \\x1c \\x0d
"""
import os
from boofuzz import (Session, Target, SocketConnection, s_initialize, s_static,
                     s_string, s_delim, s_get)

HOST = os.environ.get("TARGET_HOST", "chameleon.lab.internal")
PORT = int(os.environ.get("HL7_PORT", "2575"))
DB   = "/work/crashes/hl7_boofuzz.db"


def define_adt_a01():
    s_initialize("ADT_A01")
    s_static("\x0b")                       # MLLP start block
    s_static("MSH")
    s_delim("|"); s_string("^~\\&")        # encoding characters (fuzzed)
    s_delim("|"); s_string("SENDING_APP")
    s_delim("|"); s_string("SENDING_FAC")
    s_delim("|"); s_string("RECEIVING_APP")
    s_delim("|"); s_string("RECEIVING_FAC")
    s_delim("|"); s_string("20260101000000")
    s_delim("|"); s_string("")
    s_delim("|"); s_string("ADT^A01")      # message type
    s_delim("|"); s_string("MSG00001")     # control id
    s_delim("|"); s_string("P")
    s_delim("|"); s_string("2.5")          # version
    s_static("\r")
    s_static("PID")
    s_delim("|"); s_string("1")
    s_delim("|"); s_string("")
    s_delim("|"); s_string("PATID1234")    # patient identifier (fuzzed)
    s_delim("|"); s_string("")
    s_delim("|"); s_string("DOE^JOHN")     # patient name (fuzzed)
    s_static("\x1c\x0d")                   # MLLP end block + CR


if __name__ == "__main__":
    define_adt_a01()
    session = Session(
        target=Target(connection=SocketConnection(HOST, PORT, proto="tcp")),
        db_filename=DB,
    )
    session.connect(s_get("ADT_A01"))
    print(f"[*] Fuzzing HL7 MLLP at {HOST}:{PORT}  (results -> {DB})")
    session.fuzz()
