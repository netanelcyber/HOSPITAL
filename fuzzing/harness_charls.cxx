// libFuzzer harness — CharLS (JPEG-LS) decode from an in-memory buffer.
//
// SUSP-BIO-05: CharLS is the JPEG-LS codec embedded by DICOM stacks (incl.
// DCMTK's dcmjpls) for the "JPEG-LS Lossless/Near-Lossless" transfer syntaxes.
// A crash under ASan/UBSan here is a memory-safety bug in CharLS itself.
//
// Uses the modern C++ decoder API. CharLS throws charls::jpegls_error (and
// std::bad_alloc) on malformed input by design; those are non-crash outcomes we
// swallow so only genuine memory-safety faults abort.
//
// A destination-size cap keeps a malformed header from making the HARNESS OOM
// (that would be a false positive, not a library bug).
//
// Entry point: LLVMFuzzerTestOneInput (libFuzzer).

#include <cstdint>
#include <cstddef>
#include <vector>

#include <charls/charls.hpp>

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // JPEG-LS streams start with SOI (0xFFD8); a couple of markers need a few
    // bytes at minimum. Skip trivially short inputs to keep exec/s high.
    if (size < 4) {
        return 0;
    }

    try {
        charls::jpegls_decoder decoder;
        decoder.source(data, size);

        // Parse SPIFF (optional) + JPEG-LS header. Throws on malformed input.
        decoder.read_header();

        const size_t dst_size = decoder.get_destination_size();

        // Cap output at 128 MiB so a lying header can't OOM the harness. Real
        // JPEG-LS frames in DICOM are far smaller; this is not a bug filter for
        // the library, only a guard against harness self-OOM.
        if (dst_size == 0 || dst_size > (128u * 1024u * 1024u)) {
            return 0;
        }

        std::vector<uint8_t> dst(dst_size);
        decoder.decode(dst);   // <-- JPEG-LS decode actually runs here
    } catch (...) {
        // charls::jpegls_error / std::bad_alloc on bad input: expected, not a bug.
        return 0;
    }

    return 0;
}
