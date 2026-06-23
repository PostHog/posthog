import hashlib


def compute_recalc_fingerprint(config_fingerprint: str, recalculation_id: str) -> str:
    """Per-run fingerprint stamped onto ExperimentMetricResult rows so a recalculation run's results can be
    scoped without modifying the shared results model.

    Returns a 64-char SHA256 hex digest, unique per (config, run) pair. It is deliberately distinct from the
    config fingerprint used by the timeseries workflow, which keys its own reads off the config hash.
    """
    return hashlib.sha256(f"{config_fingerprint}{recalculation_id}".encode()).hexdigest()
