"""Generate a MIMIC-IV-schema cohort at scale, for benchmarking and tuning.

**This is not patient data and must never be presented as such.** It exists to
answer two questions that the 406-stay demo subsets cannot:

1. Does the ingestion path actually survive a million stays — the chunked
   reader, the pivot, the join — in bounded memory?
2. What hyperparameters are appropriate at that scale? Depth and estimator
   counts tuned on a few hundred rows are meaningless; trees that cannot
   overfit 250 stays will badly underfit 700,000.

It writes real CSV files in MIMIC-IV's `hosp/` layout so the ordinary
`MimicIVAdapter` reads it unmodified. Benchmarking through a mock would measure
the mock.

Marginal distributions are drawn to resemble published adult inpatient ranges,
and the outcome is a deliberate function of a few analytes. That makes the
achievable AUC an artifact of the generator, not evidence about medicine — the
number to trust from this run is throughput and memory, not discrimination.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import time
from pathlib import Path

import numpy as np
import pandas as pd

logger = logging.getLogger("scale")

# itemid -> (name, mean, sd, lower clip). itemids match MIMIC_LABITEM_MAP so the
# real adapter's filter applies unchanged.
ANALYTES = {
    50931: ("glucose", 118.0, 45.0, 20.0),
    51222: ("hemoglobin", 12.6, 2.2, 3.0),
    50971: ("potassium", 4.1, 0.65, 1.5),
    50983: ("sodium", 138.5, 5.5, 100.0),
    50912: ("creatinine", 1.15, 0.95, 0.15),
    51006: ("blood_urea_nitrogen", 21.0, 15.0, 2.0),
    51265: ("platelet_count", 240.0, 95.0, 5.0),
    51301: ("white_blood_cell_count", 9.2, 5.2, 0.2),
    50862: ("albumin", 3.5, 0.7, 0.8),
    50885: ("bilirubin", 0.9, 1.4, 0.1),
    50861: ("alanine_aminotransferase", 35.0, 60.0, 2.0),
    50878: ("aspartate_aminotransferase", 40.0, 70.0, 2.0),
    51221: ("hematocrit", 37.5, 6.5, 10.0),
}


def generate(
    out_dir: Path,
    n_stays: int,
    draws_per_analyte: int,
    seed: int,
    chunk: int = 100_000,
) -> None:
    """Write admissions, labevents and icustays in MIMIC-IV layout."""
    rng = np.random.default_rng(seed)
    hosp = out_dir / "hosp"
    icu = out_dir / "icu"
    hosp.mkdir(parents=True, exist_ok=True)
    icu.mkdir(parents=True, exist_ok=True)

    hadm_ids = np.arange(20_000_000, 20_000_000 + n_stays, dtype=np.int64)
    subject_ids = np.arange(10_000_000, 10_000_000 + n_stays, dtype=np.int64)

    admit = np.datetime64("2150-01-01") + rng.integers(
        0, 3650 * 24, n_stays
    ).astype("timedelta64[h]")
    los_hours = np.clip(rng.lognormal(4.4, 0.85, n_stays), 6, 24 * 60)
    discharge = admit + los_hours.astype("timedelta64[h]")

    # Per-stay latent severity drives both the labs and the outcome, so the
    # analytes correlate with each other the way they do in real panels rather
    # than varying independently.
    severity = rng.normal(0.0, 1.0, n_stays)

    logger.info("Writing admissions (%d rows)", n_stays)
    admissions = pd.DataFrame(
        {
            "subject_id": subject_ids,
            "hadm_id": hadm_ids,
            "admittime": admit,
            "dischtime": discharge,
            "admission_type": rng.choice(
                ["EW EMER.", "URGENT", "ELECTIVE", "OBSERVATION ADMIT"],
                n_stays,
                p=[0.55, 0.15, 0.20, 0.10],
            ),
            "admission_location": rng.choice(
                ["EMERGENCY ROOM", "PHYSICIAN REFERRAL", "TRANSFER FROM HOSPITAL"],
                n_stays,
                p=[0.62, 0.28, 0.10],
            ),
            "insurance": rng.choice(["Medicare", "Private", "Medicaid"], n_stays),
            "race": rng.choice(["WHITE", "BLACK", "HISPANIC", "ASIAN", "OTHER"], n_stays),
        }
    )

    # Outcome: severity plus renal and inflammatory contributions, at roughly
    # the 12% event rate seen in adult inpatient deterioration cohorts.
    logit = -2.6 + 1.15 * severity + rng.normal(0, 0.6, n_stays)
    deteriorated = rng.random(n_stays) < 1 / (1 + np.exp(-logit))

    admissions["hospital_expire_flag"] = 0
    died = deteriorated & (rng.random(n_stays) < 0.45)
    admissions.loc[died, "hospital_expire_flag"] = 1
    admissions["deathtime"] = pd.NaT
    admissions.loc[died, "deathtime"] = (
        admit[died] + (72 + rng.integers(0, 72, died.sum())).astype("timedelta64[h]")
    )
    admissions.to_csv(hosp / "admissions.csv", index=False)

    # ICU transfers: the rest of the deterioration events. Transfer time falls
    # after the 24h observation window so the label stays predictable.
    transferred = deteriorated & ~died
    n_icu = int(transferred.sum())
    logger.info("Writing icustays (%d rows)", n_icu)
    pd.DataFrame(
        {
            "subject_id": subject_ids[transferred],
            "hadm_id": hadm_ids[transferred],
            "stay_id": np.arange(30_000_000, 30_000_000 + n_icu),
            "intime": admit[transferred]
                      + (26 + rng.integers(0, 46, n_icu)).astype("timedelta64[h]"),
            "outtime": admit[transferred]
                       + (100 + rng.integers(0, 200, n_icu)).astype("timedelta64[h]"),
        }
    ).to_csv(icu / "icustays.csv", index=False)

    # labevents is the table that matters for the memory test: it is written in
    # chunks and must be read back in chunks.
    total_rows = n_stays * len(ANALYTES) * draws_per_analyte
    logger.info(
        "Writing labevents (~%.1fM rows) in chunks of %d stays",
        total_rows / 1e6, chunk,
    )

    lab_path = hosp / "labevents.csv"
    header_written = False
    started = time.monotonic()

    for start in range(0, n_stays, chunk):
        stop = min(start + chunk, n_stays)
        size = stop - start
        block_severity = severity[start:stop]
        block_admit = admit[start:stop]

        frames = []
        for itemid, (name, mean, sd, floor) in ANALYTES.items():
            # Renal and inflammatory markers track severity; the rest are noise,
            # which is what makes feature selection a real task.
            loading = {
                "creatinine": 0.85, "blood_urea_nitrogen": 0.70,
                "white_blood_cell_count": 0.55, "platelet_count": -0.45,
                "hemoglobin": -0.35, "albumin": -0.40, "bilirubin": 0.30,
            }.get(name, 0.0)

            for draw in range(draws_per_analyte):
                values = np.clip(
                    mean + sd * (loading * block_severity + rng.normal(0, 1, size)),
                    floor,
                    None,
                )
                frames.append(
                    pd.DataFrame(
                        {
                            "subject_id": np.repeat(subject_ids[start:stop], 1),
                            "hadm_id": hadm_ids[start:stop],
                            "itemid": itemid,
                            "charttime": block_admit
                                         + (draw * 8 + rng.integers(0, 6, size))
                                         .astype("timedelta64[h]"),
                            "valuenum": np.round(values, 2),
                        }
                    )
                )

        block = pd.concat(frames, ignore_index=True)

        # Real panels are incomplete, and which tests were ordered is itself
        # informative — a complete panel for every stay would remove that.
        block = block[rng.random(len(block)) > 0.18]

        block.to_csv(lab_path, mode="a" if header_written else "w",
                     header=not header_written, index=False)
        header_written = True
        logger.info("  %d/%d stays", stop, n_stays)

    elapsed = time.monotonic() - started
    size_gb = lab_path.stat().st_size / 1e9
    logger.info("labevents: %.2f GB in %.0fs", size_gb, elapsed)
    logger.info("Event rate: %.1f%%", 100 * deteriorated.mean())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="/tmp/scale_mimic", type=Path)
    parser.add_argument("--stays", type=int, default=1_000_000)
    parser.add_argument("--draws", type=int, default=2)
    parser.add_argument("--seed", type=int, default=11)
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    if args.clean and args.out.exists():
        shutil.rmtree(args.out)

    generate(args.out, args.stays, args.draws, args.seed)
    print(f"\nCohort written to {args.out}")


if __name__ == "__main__":
    main()
