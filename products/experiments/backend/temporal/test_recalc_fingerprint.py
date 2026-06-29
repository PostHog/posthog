from products.experiments.backend.temporal.recalc_fingerprint import compute_recalc_fingerprint


def test_recalc_fingerprint_is_deterministic_for_a_given_config():
    # The recalc fingerprint must NOT depend on the recalculation run: a stopped experiment re-recalculated
    # pins the same query_to, so a run-dependent fingerprint produced a new value each run and collided on the
    # (experiment, metric_uuid, query_to) unique constraint. Same config in, same fingerprint out, every run.
    config_fp = "a" * 64
    assert compute_recalc_fingerprint(config_fp) == compute_recalc_fingerprint(config_fp)


def test_recalc_fingerprint_differs_from_the_bare_config_fingerprint():
    # It must stay distinct from the config fingerprint the timeseries workflow stores, so recalc rows never
    # leak into the timeseries read (which filters by the bare config fingerprint).
    config_fp = "b" * 64
    assert compute_recalc_fingerprint(config_fp) != config_fp


def test_recalc_fingerprint_differs_per_config():
    assert compute_recalc_fingerprint("c" * 64) != compute_recalc_fingerprint("d" * 64)


def test_recalc_fingerprint_is_sha256_hex_length():
    assert len(compute_recalc_fingerprint("e" * 64)) == 64
