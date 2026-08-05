# Seed corpus

Coverage-guided fuzzers start from **valid** inputs and mutate them. Seeds here must be
well-formed JPEG2000 so the fuzzer reaches deep decoder code quickly.

**These are valid images, not exploits.** Do not place crash reproducers here.

## ⚠️ The default Docker build ships NO **JPEG2000** seeds here

- **CharLS (JPEG-LS):** ✅ fine out of the box — CharLS ships its `*.jls` conformance
  images **in-tree** (not a submodule), so the `--depth 1` clone includes them and
  `build.sh` copies the ~29 seeds. The `charls`/`charls_asan` campaigns are seeded.
- **OpenJPEG / GDCM (JPEG2000):** ⚠️ **seedless** by default — their sample images live
  in **test-data submodules** that a `--depth 1` clone omits, so `build.sh`'s
  `find ... -exec cp` finds no `*.j2k`/`*.jp2`/J2K-`*.dcm` (see `../README.md` →
  "Seeds matter more than anything" and `../RESULTS.md`). You must populate these
  yourself before a real JPEG2000 hunt.

## How to actually get seeds

- **Recursive submodules** (gets the upstream conformance/test data):
  ```bash
  git clone --recurse-submodules https://github.com/uclouvain/openjpeg.git
  git clone --recurse-submodules https://github.com/malaterre/GDCM.git   # gdcmData
  git clone --recurse-submodules https://github.com/team-charls/charls.git
  # copy their *.j2k / *.jp2 / *.dcm / *.jls into this dir
  ```
- **Generate** (build the tools separately — they are NOT in the fuzz image, which
  sets `BUILD_CODEC=OFF` / `GDCM_BUILD_APPLICATIONS=OFF`):
  ```bash
  opj_compress -i some.pnm -o seed.j2k
  gdcmconv --j2k in.dcm seed_j2k.dcm     # J2K-encapsulated DICOM for the GDCM harness
  ```

**These are valid images, not exploits.** Do not place crash reproducers here.

## Provenance

Record where each non-generated seed came from (project + license) so the corpus is
reproducible and redistributable. Seeds pulled from OpenJPEG/GDCM/CharLS test trees
carry those projects' licenses.

`build.sh` copies any `*.j2k`/`*.jp2`/`*.dcm`/`*.jls` it finds under `/src/*`. In a
shallow clone that yields the CharLS `*.jls` (in-tree) but typically **no** JPEG2000
test data (submodule-only) — treat JPEG2000 auto-population as best-effort, not
guaranteed.
