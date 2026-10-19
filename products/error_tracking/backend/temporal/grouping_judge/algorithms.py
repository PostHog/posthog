from collections.abc import Callable

from posthog.dataclasses import frozen

from products.error_tracking.backend.temporal.grouping_judge.types import Decision


@frozen
class GroupingAlgorithm:
    id: str
    decide: Callable[[float], Decision]


# A fixed copy of the live threshold. A change to the live threshold is a new algorithm, so rows
# recorded under this id stay comparable.
EMBEDDING_THRESHOLD_V1_DISTANCE = 0.019

EMBEDDING_THRESHOLD_V1 = GroupingAlgorithm(
    id="embedding_threshold_v1",
    decide=lambda distance: "merge" if distance < EMBEDDING_THRESHOLD_V1_DISTANCE else "no_merge",
)

ALGORITHMS: tuple[GroupingAlgorithm, ...] = (EMBEDDING_THRESHOLD_V1,)
# The algorithm production runs. Point this at another entry when production switches algorithm.
LIVE_ALGORITHM = EMBEDDING_THRESHOLD_V1


def decisions_for(distance: float, algorithms: tuple[GroupingAlgorithm, ...] = ALGORITHMS) -> dict[str, Decision]:
    return {algorithm.id: algorithm.decide(distance) for algorithm in algorithms}
