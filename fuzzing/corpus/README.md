# Seed corpus

Coverage-guided fuzzers start from **valid** inputs and mutate them. Seeds here must be
well-formed JPEG2000 so the fuzzer reaches deep decoder code quickly.

**These are valid images, not exploits.** Do not place crash reproducers here.

## ⚠️ The default Docker build ships NO seeds here

The `Dockerfile` clones OpenJPEG/GDCM/CharLS with `--depth 1` and **without their
test-data submodules**, so their sample images are **not** present in `/src/*`.
`build.sh`'s `find ... -exec cp` therefore usually copies **nothing**, and a first
run is effectively **seedless** (see `../README.md` → "Seeds matter more than
anything" and `../RESULTS.md`). You must populate seeds yourself before a real hunt.

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

`build.sh` *attempts* to copy any `*.j2k`/`*.jp2`/`*.dcm`/`*.jls` it finds under
`/src/*`, but with shallow clones there usually are none — treat auto-population as
best-effort, not guaranteed.
