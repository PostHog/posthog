import math

from products.signals.backend.temporal.parallel_grouping import (
    _assign_batch_levels,
    _compute_dependencies,
    _group_into_batches,
    _would_be_candidate,
    partition_into_parallel_batches,
)
from products.signals.backend.temporal.types import SignalCandidate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_candidate(distance: float, report_id: str = "r1") -> SignalCandidate:
    return SignalCandidate(
        signal_id="s",
        report_id=report_id,
        content="c",
        source_product="p",
        source_type="t",
        distance=distance,
    )


def _unit_vec(angle_degrees: float) -> list[float]:
    """Return a 2-D unit vector at the given angle."""
    rad = math.radians(angle_degrees)
    return [math.cos(rad), math.sin(rad)]


# ---------------------------------------------------------------------------
# _would_be_candidate
# ---------------------------------------------------------------------------


class TestWouldBeCandidate:
    def test_fewer_than_limit_candidates_always_true(self):
        """When a query has fewer than `limit` candidates, any embedding qualifies."""
        query_embs = [[1.0, 0.0]]
        ch_candidates = [[_make_candidate(0.01)]]  # 1 candidate, limit=10
        # Even a totally orthogonal embedding should qualify
        assert _would_be_candidate(query_embs, ch_candidates, [0.0, 1.0], limit=10) is True

    def test_empty_candidates_always_true(self):
        query_embs = [[1.0, 0.0]]
        ch_candidates: list[list[SignalCandidate]] = [[]]
        assert _would_be_candidate(query_embs, ch_candidates, [0.0, 1.0], limit=10) is True

    def test_full_candidates_closer_than_worst_returns_true(self):
        """Embedding closer than the worst candidate should qualify."""
        query_embs = [[1.0, 0.0]]
        # 2 candidates at distances 0.1 and 0.5
        ch_candidates = [[_make_candidate(0.1), _make_candidate(0.5)]]
        # Identical to query → distance ≈ 0 → definitely closer than 0.5
        assert _would_be_candidate(query_embs, ch_candidates, [1.0, 0.0], limit=2) is True

    def test_full_candidates_farther_than_worst_returns_false(self):
        """Embedding farther than the worst candidate should not qualify."""
        query_embs = [[1.0, 0.0]]
        # 2 candidates with very small distances
        ch_candidates = [[_make_candidate(0.001), _make_candidate(0.002)]]
        # Orthogonal embedding → distance ≈ 1.0 → worse than 0.002
        assert _would_be_candidate(query_embs, ch_candidates, [0.0, 1.0], limit=2) is False

    def test_multiple_queries_any_match_returns_true(self):
        """If any query's candidate set would accept the embedding, return True."""
        # First query: full, very tight candidates → won't accept orthogonal
        # Second query: only 1 candidate → always accepts
        query_embs = [[1.0, 0.0], [0.0, 1.0]]
        ch_candidates = [
            [_make_candidate(0.001), _make_candidate(0.002)],
            [_make_candidate(0.5)],  # under limit
        ]
        assert _would_be_candidate(query_embs, ch_candidates, [0.0, 1.0], limit=2) is True

    def test_multiple_queries_none_match_returns_false(self):
        """If no query's candidate set would accept the embedding, return False."""
        query_embs = [[1.0, 0.0], [0.0, 1.0]]
        ch_candidates = [
            [_make_candidate(0.001), _make_candidate(0.002)],
            [_make_candidate(0.001), _make_candidate(0.002)],
        ]
        # Embedding at 45° has cosine distance ~0.29 from both axes — worse than 0.002
        emb = _unit_vec(45)
        assert _would_be_candidate(query_embs, ch_candidates, emb, limit=2) is False

    def test_limit_one_exact_boundary(self):
        """With limit=1 and one candidate, embedding must beat the worst distance."""
        query_embs = [[1.0, 0.0]]
        ch_candidates = [[_make_candidate(0.3)]]
        # Identical → distance 0 → beats 0.3
        assert _would_be_candidate(query_embs, ch_candidates, [1.0, 0.0], limit=1) is True
        # Orthogonal → distance 1.0 → does not beat 0.3
        assert _would_be_candidate(query_embs, ch_candidates, [0.0, 1.0], limit=1) is False


# ---------------------------------------------------------------------------
# _assign_batch_levels
# ---------------------------------------------------------------------------


class TestAssignBatchLevels:
    def test_no_deps(self):
        assert _assign_batch_levels([set(), set(), set()]) == [0, 0, 0]

    def test_single_dep(self):
        # B depends on A
        assert _assign_batch_levels([set(), {0}]) == [0, 1]

    def test_linear_chain(self):
        # A → B → C
        assert _assign_batch_levels([set(), {0}, {1}]) == [0, 1, 2]

    def test_diamond(self):
        # A, B independent; C depends on both; D depends on C
        deps: list[set[int]] = [set(), set(), {0, 1}, {2}]
        assert _assign_batch_levels(deps) == [0, 0, 1, 2]

    def test_wide_fan_in(self):
        # 0,1,2 independent; 3 depends on all three
        deps: list[set[int]] = [set(), set(), set(), {0, 1, 2}]
        assert _assign_batch_levels(deps) == [0, 0, 0, 1]

    def test_single_signal(self):
        assert _assign_batch_levels([set()]) == [0]

    def test_skip_level(self):
        # 0 independent; 1 depends on 0 (level 1); 2 depends on 1 (level 2);
        # 3 depends on 0 only (level 1, not 2)
        deps: list[set[int]] = [set(), {0}, {1}, {0}]
        assert _assign_batch_levels(deps) == [0, 1, 2, 1]

    def test_complex_dag(self):
        # 0: no deps → 0
        # 1: no deps → 0
        # 2: depends on 0 → 1
        # 3: depends on 1 → 1
        # 4: depends on 2 and 3 → 2
        deps: list[set[int]] = [set(), set(), {0}, {1}, {2, 3}]
        assert _assign_batch_levels(deps) == [0, 0, 1, 1, 2]


# ---------------------------------------------------------------------------
# _group_into_batches
# ---------------------------------------------------------------------------


class TestGroupIntoBatches:
    def test_empty(self):
        assert _group_into_batches([]) == []

    def test_all_same_level(self):
        assert _group_into_batches([0, 0, 0]) == [[0, 1, 2]]

    def test_all_different_levels(self):
        assert _group_into_batches([0, 1, 2]) == [[0], [1], [2]]

    def test_mixed(self):
        # levels: 0, 0, 1, 1, 2
        assert _group_into_batches([0, 0, 1, 1, 2]) == [[0, 1], [2, 3], [4]]

    def test_preserves_index_order_within_batch(self):
        # Indices within each batch should be in ascending order
        levels = [0, 1, 0, 1, 0]
        batches = _group_into_batches(levels)
        assert batches == [[0, 2, 4], [1, 3]]

    def test_single_signal(self):
        assert _group_into_batches([0]) == [[0]]

    def test_gaps_in_levels_produce_empty_batches(self):
        # Levels 0 and 2 — level 1 batch should be empty
        # (This shouldn't happen from _assign_batch_levels but _group_into_batches
        # should handle it correctly)
        levels = [0, 2]
        batches = _group_into_batches(levels)
        assert batches == [[0], [], [1]]


# ---------------------------------------------------------------------------
# _compute_dependencies
# ---------------------------------------------------------------------------


class TestComputeDependencies:
    def test_identical_signals_are_dependent(self):
        """Two identical signals should depend on each other (1 depends on 0)."""
        emb = [1.0, 0.0]
        # Each signal has one query. Fewer than limit candidates → always dependent.
        per_signal_query_embs = [[[1.0, 0.0]], [[1.0, 0.0]]]
        per_signal_ch: list[list[list[SignalCandidate]]] = [[[]], [[]]]
        deps = _compute_dependencies(per_signal_query_embs, per_signal_ch, [emb, emb], limit=10)
        assert deps[0] == set()  # first signal has no earlier signals
        assert deps[1] == {0}

    def test_orthogonal_signals_with_full_tight_candidates_independent(self):
        """Signals with orthogonal embeddings and full, tight candidate lists are independent."""
        emb_a = [1.0, 0.0]
        emb_b = [0.0, 1.0]
        # Each has one query with full, very tight candidates
        per_signal_query_embs = [[[1.0, 0.0]], [[0.0, 1.0]]]
        per_signal_ch = [
            [[_make_candidate(0.001), _make_candidate(0.002)]],
            [[_make_candidate(0.001), _make_candidate(0.002)]],
        ]
        deps = _compute_dependencies(per_signal_query_embs, per_signal_ch, [emb_a, emb_b], limit=2)
        assert deps[0] == set()
        assert deps[1] == set()

    def test_dependency_is_directional(self):
        """Signal 0 never depends on signal 1 (only earlier → later)."""
        emb = [1.0, 0.0]
        per_signal_query_embs = [[[1.0, 0.0]], [[1.0, 0.0]]]
        per_signal_ch: list[list[list[SignalCandidate]]] = [[[]], [[]]]
        deps = _compute_dependencies(per_signal_query_embs, per_signal_ch, [emb, emb], limit=10)
        assert 1 not in deps[0]

    def test_chain_dependency(self):
        """A chain: 3 similar signals with sparse candidates → 1 depends on 0, 2 depends on 0,1."""
        emb = [1.0, 0.0]
        per_signal_query_embs = [[[1.0, 0.0]], [[1.0, 0.0]], [[1.0, 0.0]]]
        per_signal_ch: list[list[list[SignalCandidate]]] = [[[]], [[]], [[]]]
        deps = _compute_dependencies(per_signal_query_embs, per_signal_ch, [emb, emb, emb], limit=10)
        assert deps[0] == set()
        assert deps[1] == {0}
        assert deps[2] == {0, 1}

    def test_partial_dependency(self):
        """Signal 2 depends on 0 but not on 1 (1 is orthogonal with tight candidates)."""
        emb_a = [1.0, 0.0]  # signal 0
        emb_b = [0.0, 1.0]  # signal 1
        emb_c = [1.0, 0.0]  # signal 2 — same as 0

        per_signal_query_embs = [
            [[1.0, 0.0]],
            [[0.0, 1.0]],
            [[1.0, 0.0]],  # signal 2 queries along same direction as signal 0
        ]
        per_signal_ch = [
            [[_make_candidate(0.001), _make_candidate(0.002)]],
            [[_make_candidate(0.001), _make_candidate(0.002)]],
            [[_make_candidate(0.001), _make_candidate(0.002)]],
        ]
        deps = _compute_dependencies(per_signal_query_embs, per_signal_ch, [emb_a, emb_b, emb_c], limit=2)
        assert deps[2] == {0}  # signal 0 is close to signal 2's query
        assert 1 not in deps[2]  # signal 1 is orthogonal

    def test_empty_batch(self):
        deps = _compute_dependencies([], [], [], limit=10)
        assert deps == []

    def test_single_signal(self):
        deps = _compute_dependencies([[[1.0, 0.0]]], [[[]]], [[1.0, 0.0]], limit=10)
        assert deps == [set()]


# ---------------------------------------------------------------------------
# partition_into_parallel_batches (integration of the above)
# ---------------------------------------------------------------------------


class TestPartitionIntoParallelBatches:
    def test_all_independent_single_batch(self):
        """Orthogonal signals with full tight candidates → all in one batch."""
        embs = [[1.0, 0.0], [0.0, 1.0]]
        per_signal_query_embs = [[[1.0, 0.0]], [[0.0, 1.0]]]
        per_signal_ch = [
            [[_make_candidate(0.001), _make_candidate(0.002)]],
            [[_make_candidate(0.001), _make_candidate(0.002)]],
        ]
        batches = partition_into_parallel_batches(per_signal_query_embs, per_signal_ch, embs, limit=2)
        assert batches == [[0, 1]]

    def test_all_dependent_sequential(self):
        """Identical signals with sparse candidates → linear chain of single-element batches."""
        emb = [1.0, 0.0]
        n = 4
        per_signal_query_embs = [[[1.0, 0.0]]] * n
        per_signal_ch: list[list[list[SignalCandidate]]] = [[[]] for _ in range(n)]
        batches = partition_into_parallel_batches(per_signal_query_embs, per_signal_ch, [emb] * n, limit=10)
        # Each signal depends on all earlier ones → levels 0, 1, 2, 3
        assert batches == [[0], [1], [2], [3]]

    def test_two_clusters(self):
        """Two clusters of similar signals, orthogonal to each other.
        Within a cluster, signals are dependent (sparse candidates).
        Across clusters, signals are independent (tight candidates block the other cluster).
        """
        emb_x = [1.0, 0.0]
        emb_y = [0.0, 1.0]
        # Signal 0: cluster X, Signal 1: cluster Y, Signal 2: cluster X, Signal 3: cluster Y
        embs = [emb_x, emb_y, emb_x, emb_y]
        per_signal_query_embs = [
            [[1.0, 0.0]],
            [[0.0, 1.0]],
            [[1.0, 0.0]],
            [[0.0, 1.0]],
        ]
        # Full, tight candidates along each signal's own direction
        per_signal_ch = [
            [[_make_candidate(0.001, "rx"), _make_candidate(0.002, "rx")]],
            [[_make_candidate(0.001, "ry"), _make_candidate(0.002, "ry")]],
            [[_make_candidate(0.001, "rx"), _make_candidate(0.002, "rx")]],
            [[_make_candidate(0.001, "ry"), _make_candidate(0.002, "ry")]],
        ]
        batches = partition_into_parallel_batches(per_signal_query_embs, per_signal_ch, embs, limit=2)
        # 0: level 0 (no deps)
        # 1: level 0 (1's query is [0,1], signal 0's emb is [1,0] → dist=1.0 > 0.002 → no dep)
        # 2: level 1 (2's query is [1,0], signal 0's emb is [1,0] → dist=0.0 < 0.002 → dep on 0;
        #             signal 1's emb is [0,1] → dist=1.0 > 0.002 → no dep on 1)
        # 3: level 1 (3's query is [0,1], signal 1's emb is [0,1] → dist=0.0 < 0.002 → dep on 1;
        #             signal 0's emb is [1,0] → dist=1.0 → no dep; signal 2's emb → dist=1.0 → no dep)
        assert batches == [[0, 1], [2, 3]]

    def test_empty(self):
        assert partition_into_parallel_batches([], [], [], limit=10) == []

    def test_single_signal(self):
        batches = partition_into_parallel_batches([[[1.0, 0.0]]], [[[]]], [[1.0, 0.0]], limit=10)
        assert batches == [[0]]

    def test_diamond_pattern(self):
        """
        Signal 0: independent
        Signal 1: independent (orthogonal to 0, full tight candidates)
        Signal 2: depends on both 0 and 1 (sparse candidates, any embedding qualifies)
        Signal 3: depends on 2 (same direction, will be candidate)

        Expected: batch 0 = [0, 1], batch 1 = [2], batch 2 = [3]
        """
        embs = [
            [1.0, 0.0],  # 0
            [0.0, 1.0],  # 1
            [0.7, 0.7],  # 2
            [0.7, 0.7],  # 3 (same as 2)
        ]
        per_signal_query_embs = [
            [[1.0, 0.0]],
            [[0.0, 1.0]],
            [[0.7, 0.7]],  # sparse candidates → accepts anything
            [[0.7, 0.7]],  # sparse candidates → accepts anything
        ]
        per_signal_ch: list[list[list[SignalCandidate]]] = [
            [[_make_candidate(0.001), _make_candidate(0.002)]],
            [[_make_candidate(0.001), _make_candidate(0.002)]],
            [[]],  # no CH candidates → always accepts
            [[]],  # no CH candidates → always accepts
        ]
        batches = partition_into_parallel_batches(per_signal_query_embs, per_signal_ch, embs, limit=2)
        # Signal 2: depends on 0 and 1 (sparse, accepts all) → level max(0,0)+1 = 1
        # Signal 3: depends on 0, 1, and 2 (sparse, accepts all) → level max(0,0,1)+1 = 2
        assert batches == [[0, 1], [2], [3]]

    def test_all_signals_covered(self):
        """Every signal index appears exactly once across all batches."""
        emb = [1.0, 0.0]
        n = 7
        per_signal_query_embs = [[[1.0, 0.0]]] * n
        per_signal_ch: list[list[list[SignalCandidate]]] = [[[]] for _ in range(n)]
        batches = partition_into_parallel_batches(per_signal_query_embs, per_signal_ch, [emb] * n, limit=10)
        all_indices = [idx for batch in batches for idx in batch]
        assert sorted(all_indices) == list(range(n))

    def test_batch_ordering_respects_dependencies(self):
        """For every signal in batch k, all its dependencies are in batches < k."""
        emb = [1.0, 0.0]
        n = 5
        per_signal_query_embs = [[[1.0, 0.0]]] * n
        per_signal_ch: list[list[list[SignalCandidate]]] = [[[]] for _ in range(n)]
        embs = [emb] * n
        batches = partition_into_parallel_batches(per_signal_query_embs, per_signal_ch, embs, limit=10)

        # Build index → batch mapping
        idx_to_batch: dict[int, int] = {}
        for batch_num, indices in enumerate(batches):
            for idx in indices:
                idx_to_batch[idx] = batch_num

        # Recompute deps and verify
        deps = _compute_dependencies(per_signal_query_embs, per_signal_ch, embs, limit=10)
        for j in range(n):
            for dep in deps[j]:
                assert idx_to_batch[dep] < idx_to_batch[j], (
                    f"Signal {j} (batch {idx_to_batch[j]}) depends on signal {dep} "
                    f"(batch {idx_to_batch[dep]}) which is not in an earlier batch"
                )

    def test_no_intra_batch_dependencies(self):
        """No two signals in the same batch should be dependent on each other."""
        embs = [
            [1.0, 0.0],
            [0.0, 1.0],
            [1.0, 0.0],
            [0.0, 1.0],
        ]
        per_signal_query_embs = [
            [[1.0, 0.0]],
            [[0.0, 1.0]],
            [[1.0, 0.0]],
            [[0.0, 1.0]],
        ]
        per_signal_ch = [
            [[_make_candidate(0.001), _make_candidate(0.002)]],
            [[_make_candidate(0.001), _make_candidate(0.002)]],
            [[_make_candidate(0.001), _make_candidate(0.002)]],
            [[_make_candidate(0.001), _make_candidate(0.002)]],
        ]
        batches = partition_into_parallel_batches(per_signal_query_embs, per_signal_ch, embs, limit=2)
        deps = _compute_dependencies(per_signal_query_embs, per_signal_ch, embs, limit=2)

        for batch_indices in batches:
            batch_set = set(batch_indices)
            for j in batch_indices:
                assert deps[j].isdisjoint(batch_set), (
                    f"Signal {j} in batch {batch_indices} depends on {deps[j] & batch_set} which are in the same batch"
                )
