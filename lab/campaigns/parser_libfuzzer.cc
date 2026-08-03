// Coverage-guided file/message parser fuzzing (source-guided — the strongest,
// fully-offline method). Point it at the Chameleon routine that ingests an
// untrusted file or message.
//
// 1) Replace the extern declaration with the real parser entry point.
// 2) Build (from inside the fuzzer container):
//      clang++ -g -O1 -fsanitize=address,undefined,fuzzer \
//        /work/campaigns/parser_libfuzzer.cc <chameleon object/lib> \
//        -o /work/campaigns/parser_fuzzer
// 3) Run with a seed corpus of (synthetic) sample inputs:
//      /work/campaigns/parser_fuzzer -max_len=1048576 \
//        -artifact_prefix=/work/crashes/ /work/campaigns/corpus/
//
// ASAN/UBSAN turn memory-safety and undefined-behavior bugs into immediate,
// triageable crashes with stack traces.

#include <cstdint>
#include <cstddef>

// >>> REPLACE with the real signature of the target parser <<<
extern "C" int chameleon_parse(const uint8_t *data, size_t size);

extern "C" int LLVMFuzzerTestOneInput(const uint8_t *data, size_t size) {
  chameleon_parse(data, size);
  return 0;
}
