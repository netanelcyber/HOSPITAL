"""Deterministic placement of pipeline stages onto workers.

The pipeline is a DAG of stages that mostly do not share state: each source is
ingested independently, each ensemble backend trains independently, calibration
and export follow. So the stages *can* be split across machines or processes.
The question is how to choose the split.

**Why not `random.choice`.** "Random but fixed once chosen" is exactly what a
naive random assignment fails to give you. Re-run the scheduler and every stage
lands somewhere new; a worker joins or dies and the whole map reshuffles. Any
cached intermediate on the old worker is stranded, and a re-run of the same
cohort produces different placement, which makes a failure impossible to
reproduce.

**Rendezvous hashing (HRW)** gives the property directly. For a stage `s` and
workers `w`, compute `hash(seed, s, w)` for each worker and take the highest.
The result is:

- *pseudo-random* — the seed decorrelates placement from stage names, so
  related stages do not all pile onto one worker
- *deterministic* — same seed, same stage, same worker set, same answer, on any
  machine, in any process, forever
- *stable under membership change* — removing a worker only remaps the stages
  that were on it. Modulo hashing (`hash(s) % n`) remaps almost everything when
  `n` changes, which is why it is the wrong tool here.

Placement is computed independently by every participant rather than assigned
by a coordinator: given the same seed and worker list, they all derive the same
map, so there is no scheduler to be a single point of failure.
"""

from __future__ import annotations

import hashlib
import logging
import struct
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)


class StageKind(str, Enum):
    """Stage types, ordered by their position in the pipeline."""

    INGEST = "ingest"              # one per data source
    HARMONIZE = "harmonize"        # LOINC units, implausible-value clipping
    FEATURES_LAB = "features_lab"
    FEATURES_NLP = "features_nlp"
    TRAIN_BACKEND = "train_backend"  # one per ensemble backend
    CALIBRATE = "calibrate"
    EVALUATE = "evaluate"
    EXPORT_BUNDLE = "export_bundle"


@dataclass(frozen=True)
class Stage:
    """One schedulable unit of work."""

    kind: StageKind
    key: str                                   # e.g. "mimic-iv", "xgboost"
    depends_on: Tuple[str, ...] = ()           # stage ids
    # Stages that must run where their input already is. Moving 26M lab rows
    # between machines costs more than the stage itself.
    pin_to_input: bool = False

    @property
    def id(self) -> str:
        return f"{self.kind.value}:{self.key}"

    def __repr__(self) -> str:
        return f"Stage({self.id})"


@dataclass(frozen=True)
class Worker:
    """A machine or process that can execute stages."""

    name: str
    slots: int = 1  # relative capacity; a worker with 4 slots draws ~4x the work

    def __post_init__(self) -> None:
        if self.slots < 1:
            raise ValueError(f"Worker {self.name!r} must have at least one slot")


def _hash_score(seed: int, stage_id: str, worker: str, replica: int = 0) -> int:
    """Rendezvous weight for (stage, worker).

    BLAKE2b rather than Python's `hash()`: the built-in is randomized per
    process by PYTHONHASHSEED, which would make placement differ between
    machines — destroying the one property this module exists to provide.
    """
    digest = hashlib.blake2b(
        struct.pack("<qi", seed, replica) + b"\x00" + stage_id.encode() + b"\x00" + worker.encode(),
        digest_size=8,
    ).digest()
    return int.from_bytes(digest, "big")


class StagePlacement:
    """Assigns stages to workers deterministically."""

    def __init__(self, workers: Sequence[Worker], seed: int = 42):
        if not workers:
            raise ValueError("At least one worker is required")

        names = [w.name for w in workers]
        if len(set(names)) != len(names):
            raise ValueError(f"Worker names must be unique, got {names}")

        # Sorted so the same set of workers yields the same structure whatever
        # order the caller passed them in.
        self.workers = tuple(sorted(workers, key=lambda w: w.name))
        self.seed = seed

    def assign(self, stage: Stage, exclude: Optional[Set[str]] = None) -> str:
        """The worker that owns this stage.

        A worker with `slots > 1` is entered once per slot, so capacity
        weighting falls out of the same mechanism rather than needing a second
        balancing pass.
        """
        exclude = exclude or set()
        candidates = [w for w in self.workers if w.name not in exclude]
        if not candidates:
            raise ValueError(f"No worker available for {stage.id} (all excluded)")

        best_name, best_score = None, -1
        for worker in candidates:
            for replica in range(worker.slots):
                score = _hash_score(self.seed, stage.id, worker.name, replica)
                if score > best_score:
                    best_score, best_name = score, worker.name

        return best_name

    def plan(self, stages: Sequence[Stage]) -> Dict[str, str]:
        """Map every stage id to its worker.

        Stages marked `pin_to_input` follow their first dependency rather than
        hashing independently: a feature stage that hashes away from the data
        it consumes turns a local read into a network transfer of the largest
        object in the pipeline.
        """
        placement: Dict[str, str] = {}
        by_id = {stage.id: stage for stage in stages}

        for stage in stages:
            if stage.pin_to_input and stage.depends_on:
                upstream = stage.depends_on[0]
                if upstream in placement:
                    placement[stage.id] = placement[upstream]
                    continue
                if upstream not in by_id:
                    logger.warning(
                        "%s pins to unknown dependency %r; hashing instead",
                        stage.id, upstream,
                    )
            placement[stage.id] = self.assign(stage)

        return placement

    def group_by_worker(self, stages: Sequence[Stage]) -> Dict[str, List[str]]:
        """Invert the plan: what each worker is responsible for."""
        grouped: Dict[str, List[str]] = {w.name: [] for w in self.workers}
        for stage_id, worker in self.plan(stages).items():
            grouped[worker].append(stage_id)
        return {name: sorted(ids) for name, ids in grouped.items()}

    def rebalance_cost(
        self, stages: Sequence[Stage], new_workers: Sequence[Worker]
    ) -> Dict[str, object]:
        """How many stages move if the worker set changes.

        The number that justifies rendezvous hashing over modulo: removing one
        of N workers should move roughly 1/N of stages, not nearly all of them.
        """
        before = self.plan(stages)
        after = StagePlacement(new_workers, self.seed).plan(stages)

        moved = [s for s in before if before[s] != after.get(s)]
        return {
            "total_stages": len(before),
            "moved": len(moved),
            "moved_fraction": len(moved) / len(before) if before else 0.0,
            "moved_stages": sorted(moved),
        }


def build_pipeline_stages(
    sources: Sequence[str],
    backends: Sequence[str] = ("xgboost", "lightgbm"),
    use_nlp: bool = True,
) -> List[Stage]:
    """The standard PenuX-II stage graph.

    Ingest and per-backend training are the genuinely parallel parts: sources
    share nothing, and the ensemble's backends are independent models whose
    predictions are only combined at the end. Calibration and export are
    single-node by nature — they need the assembled model.
    """
    stages: List[Stage] = []

    for source in sources:
        ingest = Stage(StageKind.INGEST, source)
        stages.append(ingest)
        # Harmonization and lab features stream the ingested frame, which is
        # the biggest object here, so they stay with it.
        harmonize = Stage(StageKind.HARMONIZE, source, (ingest.id,), pin_to_input=True)
        stages.append(harmonize)
        stages.append(
            Stage(StageKind.FEATURES_LAB, source, (harmonize.id,), pin_to_input=True)
        )
        if use_nlp:
            # NLP is CPU-bound on text and does not need the lab frame, so it
            # is free to hash elsewhere.
            stages.append(Stage(StageKind.FEATURES_NLP, source, (ingest.id,)))

    feature_ids = tuple(s.id for s in stages if s.kind.value.startswith("features"))

    for backend in backends:
        stages.append(Stage(StageKind.TRAIN_BACKEND, backend, feature_ids))

    train_ids = tuple(s.id for s in stages if s.kind is StageKind.TRAIN_BACKEND)
    stages.append(Stage(StageKind.CALIBRATE, "ensemble", train_ids))
    stages.append(Stage(StageKind.EVALUATE, "test", ("calibrate:ensemble",)))
    stages.append(Stage(StageKind.EXPORT_BUNDLE, "wasm", ("calibrate:ensemble",)))

    return stages


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    stages = build_pipeline_stages(
        sources=["mimic-iv", "mimic-iv-ed", "eicu", "hirid"],
        backends=["xgboost", "lightgbm"],
    )
    workers = [
        Worker("node-a", slots=4),
        Worker("node-b", slots=2),
        Worker("node-c", slots=2),
    ]

    placement = StagePlacement(workers, seed=42)

    print(f"{len(stages)} stages across {len(workers)} workers\n")
    for worker, assigned in placement.group_by_worker(stages).items():
        print(f"{worker}:")
        for stage_id in assigned:
            print(f"    {stage_id}")

    # Determinism: recomputing from scratch must give the same answer.
    again = StagePlacement(list(reversed(workers)), seed=42)
    assert again.plan(stages) == placement.plan(stages), "placement is not deterministic"
    print("\n✓ deterministic across process and worker ordering")

    cost = placement.rebalance_cost(stages, [w for w in workers if w.name != "node-c"])
    print(
        f"\nRemoving node-c moves {cost['moved']}/{cost['total_stages']} stages "
        f"({cost['moved_fraction']:.0%}); modulo hashing would move most of them."
    )
