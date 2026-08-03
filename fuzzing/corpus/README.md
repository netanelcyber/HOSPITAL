# Seed corpus

Coverage-guided fuzzers start from **valid** inputs and mutate them. Seeds here must be
well-formed JPEG2000 so the fuzzer reaches deep decoder code quickly.

**These are valid images, not exploits.** Do not place crash reproducers here.

## What to put here (populated at build time / manually)

- `*.j2k`, `*.jp2` — raw JPEG2000 codestreams. Good sources:
  - OpenJPEG's own `tests/` sample images (present in the cloned source at `/src/openjpeg`).
  - Self-generated: `opj_compress -i some.png -o seed.j2k`.
- `*.dcm` — JPEG2000-**encapsulated** DICOM (for the GDCM harness), e.g.
  GDCM test data, or `gdcmconv --j2k in.dcm seed_j2k.dcm`.

## Provenance

Record where each non-generated seed came from (project + license) so the corpus is
reproducible and redistributable. Seeds pulled from OpenJPEG/GDCM test trees carry those
projects' licenses.

`build.sh` auto-populates this directory from the cloned OpenJPEG/GDCM test images if it finds
them; otherwise drop a few `.j2k`/`.dcm` files here by hand before running.
