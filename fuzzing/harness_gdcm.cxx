// libFuzzer harness — GDCM DICOM read + forced pixel decode.
//
// SUSP-BIO-04 (DICOM-realistic layer): drives gdcm::ImageReader over an
// in-memory DICOM stream and then forces the pixel data to actually decode
// (GetBuffer), so the embedded JPEG2000 codec path runs. A crash under
// ASan/UBSan here is either in OpenJPEG (as embedded) or in GDCM's own wrapper
// (integer math / buffer sizing) — triage.sh classifies which from the stack.
//
// Accepts J2K-encapsulated DICOM in the corpus. Malformed input is expected and
// must be handled gracefully; GDCM signals failure via return codes and its own
// exceptions, which we swallow so only genuine memory-safety faults abort.
//
// Entry point: LLVMFuzzerTestOneInput (libFuzzer).

#include <cstdint>
#include <cstddef>
#include <string>
#include <sstream>
#include <vector>

#include "gdcmImageReader.h"
#include "gdcmImage.h"

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    // A whole DICOM object (preamble + meta + a compressed frame) needs some
    // minimum size; skip trivially short inputs to keep exec/s high.
    if (size < 132) {
        return 0;
    }

    // In-memory stream: no filesystem touch, fast, and deterministic.
    std::string buf(reinterpret_cast<const char *>(data), size);
    std::istringstream iss(buf, std::ios::binary);

    try {
        gdcm::ImageReader reader;
        reader.SetStream(iss);

        // Read() parses the dataset + image metadata. On malformed input it
        // returns false (or throws) — both are non-crash outcomes we accept.
        if (!reader.Read()) {
            return 0;
        }

        const gdcm::Image &image = reader.GetImage();

        // Force the codec to run: allocate the decoded-length buffer and pull
        // the pixels through. This is the step that exercises the JPEG2000
        // decode path (rather than just header parsing).
        const unsigned long len = image.GetBufferLength();

        // Guard against absurd sizes advertised by a malformed header so the
        // HARNESS itself doesn't OOM (that would be a false positive, not a
        // library bug). ~512 MiB ceiling is generous for real frames.
        if (len == 0 || len > (512UL * 1024UL * 1024UL)) {
            return 0;
        }

        std::vector<char> pixels(len);
        image.GetBuffer(pixels.data());  // <-- decode happens here
    } catch (...) {
        // GDCM throws on many malformed inputs by design; not a memory bug.
        return 0;
    }

    return 0;
}
