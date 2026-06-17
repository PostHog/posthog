from products.experiments.backend.temporal.recalc_fingerprint import compute_recalc_fingerprint


def test_is_deterministic():
    assert compute_recalc_fingerprint("config-fp", "run-1") == compute_recalc_fingerprint("config-fp", "run-1")


def test_differs_per_run():
    assert compute_recalc_fingerprint("config-fp", "run-1") != compute_recalc_fingerprint("config-fp", "run-2")


def test_differs_per_config():
    assert compute_recalc_fingerprint("config-fp-1", "run-1") != compute_recalc_fingerprint("config-fp-2", "run-1")


def test_is_sha256_hex_length():
    assert len(compute_recalc_fingerprint("config-fp", "run-1")) == 64
