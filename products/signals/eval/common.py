import sys
import random
from dataclasses import dataclass
from enum import Enum

from tqdm import tqdm

from products.signals.eval.data_spec import EvalSignalSpec
from products.signals.eval.fixtures.grouping_data import GROUP_DATA

RNG_SEED = 1337
MAX_CONCURRENT_RUNS = 70


class EvalProgress:
    """Encapsulates tqdm progress bars and error counters for the eval run."""

    def __init__(self, n_signals: int, n_groups: int):
        self.n_signals = n_signals
        self.n_groups = n_groups
        self.active = 0
        self.dropped = 0
        self._bar = tqdm(total=n_signals, desc="Matching", unit="sig", file=sys.stderr)

    def signal_started(self):
        self.active += 1
        self._update_postfix()

    def signal_done(self):
        self.active -= 1
        self._bar.update(1)
        self._update_postfix()

    def signal_dropped(self):
        self.active -= 1
        self.dropped += 1
        self._bar.update(1)
        self._update_postfix()

    def _update_postfix(self):
        parts: dict[str, int] = {}
        if self.active:
            parts["processing"] = self.active
        if self.dropped:
            parts["filtered"] = self.dropped
        self._bar.set_postfix(parts)

    def start_judging(self, n_reports: int):
        self._bar.close()
        self._bar = tqdm(total=n_reports, desc="Judging", unit="report", file=sys.stderr)

    def report_judged(self):
        self._bar.update(1)

    def done(self):
        self._bar.close()


class MatchFailureMode(Enum):
    NONE = "NONE"  # correct match
    UNDERGROUP = "UNDERGROUP"  # created new report when should have joined existing
    OVERGROUP = "OVERGROUP"  # joined a report belonging to a different ground-truth group


@dataclass
class EvalSignalCase:
    group_index: int
    signal_index: int
    actionable: bool
    safe: bool
    signal: EvalSignalSpec


def get_signals_stream() -> list[EvalSignalCase]:
    """Interleave signals across groups randomly, preserving within-group order."""
    rng = random.Random(RNG_SEED)
    cursors = [0] * len(GROUP_DATA)
    stream: list[EvalSignalCase] = []

    def get_active():
        return [i for i, g in enumerate(GROUP_DATA) if cursors[i] < len(g.signals)]

    while active := get_active():
        k = rng.randint(0, len(active) - 1)
        group_index = active[k]
        group = GROUP_DATA[group_index]
        signal = group.signals[cursors[group_index]]
        stream.append(
            EvalSignalCase(
                group_index=group_index,
                signal_index=cursors[group_index],
                safe=group.safe,
                actionable=group.actionable,
                signal=signal,
            )
        )
        cursors[group_index] += 1

    return stream
