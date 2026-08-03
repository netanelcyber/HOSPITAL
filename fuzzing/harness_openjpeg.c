/*
 * libFuzzer harness — OpenJPEG JPEG2000 decode from an in-memory buffer.
 *
 * SUSP-BIO-04: exercises the codec that DICOM stacks embed for the
 * "JPEG 2000 Image Compression" transfer syntaxes. A crash under ASan/UBSan
 * here is a memory-safety bug in OpenJPEG itself.
 *
 * Self-contained (does not depend on OpenJPEG's own fuzzer sources). Structure
 * mirrors the standard opj_decompress flow: memory stream -> read header ->
 * decode -> end. Every allocation is released on every path so the sanitizers
 * flag genuine faults, not harness leaks.
 *
 * Entry point: LLVMFuzzerTestOneInput (libFuzzer).
 */

#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#include <openjpeg.h>

/* --- memory stream backing: OpenJPEG pulls bytes from this buffer ---------- */
typedef struct {
    const uint8_t *data;
    size_t         size;
    size_t         pos;
} mem_stream_t;

static OPJ_SIZE_T mem_read(void *out, OPJ_SIZE_T nbytes, void *user) {
    mem_stream_t *m = (mem_stream_t *)user;
    if (m->pos >= m->size) {
        return (OPJ_SIZE_T)-1; /* EOF */
    }
    size_t remaining = m->size - m->pos;
    size_t n = nbytes < remaining ? nbytes : remaining;
    memcpy(out, m->data + m->pos, n);
    m->pos += n;
    return n;
}

static OPJ_OFF_T mem_skip(OPJ_OFF_T nbytes, void *user) {
    mem_stream_t *m = (mem_stream_t *)user;
    if (nbytes < 0) {
        return -1;
    }
    size_t remaining = m->size - m->pos;
    size_t n = (size_t)nbytes < remaining ? (size_t)nbytes : remaining;
    m->pos += n;
    return (OPJ_OFF_T)n;
}

static OPJ_BOOL mem_seek(OPJ_OFF_T nbytes, void *user) {
    mem_stream_t *m = (mem_stream_t *)user;
    if (nbytes < 0 || (size_t)nbytes > m->size) {
        return OPJ_FALSE;
    }
    m->pos = (size_t)nbytes;
    return OPJ_TRUE;
}

/* Silence codec log spam so fuzzing stays fast and output stays readable. */
static void quiet(const char *msg, void *client) { (void)msg; (void)client; }

/* Pick the codec from the leading magic bytes (JP2 box vs raw J2K codestream). */
static OPJ_CODEC_FORMAT sniff(const uint8_t *d, size_t n) {
    static const uint8_t jp2_rfc3745[] =
        {0x00,0x00,0x00,0x0C,0x6A,0x50,0x20,0x20,0x0D,0x0A,0x87,0x0A};
    static const uint8_t jp2_bare[]    = {0x0D,0x0A,0x87,0x0A};
    static const uint8_t j2k_magic[]   = {0xFF,0x4F,0xFF,0x51};
    if (n >= 12 && memcmp(d, jp2_rfc3745, 12) == 0) return OPJ_CODEC_JP2;
    if (n >= 4  && memcmp(d, jp2_bare,    4)  == 0) return OPJ_CODEC_JP2;
    if (n >= 4  && memcmp(d, j2k_magic,   4)  == 0) return OPJ_CODEC_J2K;
    return OPJ_CODEC_J2K; /* default: try to parse as a raw codestream */
}

int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
    if (size < 4) {
        return 0;
    }

    mem_stream_t mem = { data, size, 0 };

    opj_stream_t *stream = opj_stream_default_create(OPJ_TRUE /* read-only */);
    if (!stream) {
        return 0;
    }
    opj_stream_set_user_data(stream, &mem, NULL);
    opj_stream_set_user_data_length(stream, (OPJ_UINT64)size);
    opj_stream_set_read_function(stream, mem_read);
    opj_stream_set_skip_function(stream, mem_skip);
    opj_stream_set_seek_function(stream, mem_seek);

    opj_codec_t *codec = opj_create_decompress(sniff(data, size));
    if (!codec) {
        opj_stream_destroy(stream);
        return 0;
    }
    opj_set_info_handler(codec, quiet, NULL);
    opj_set_warning_handler(codec, quiet, NULL);
    opj_set_error_handler(codec, quiet, NULL);

    opj_dparameters_t params;
    opj_set_default_decoder_parameters(&params);

    opj_image_t *image = NULL;
    if (opj_setup_decoder(codec, &params) &&
        opj_read_header(stream, codec, &image) &&
        image) {
        /* Full decode is where most parsing/allocation bugs surface. */
        if (opj_decode(codec, stream, image)) {
            opj_end_decompress(codec, stream);
        }
    }

    if (image) {
        opj_image_destroy(image);
    }
    opj_destroy_codec(codec);
    opj_stream_destroy(stream);
    return 0;
}
