DEFAULT_INFRA_RETRIES = 2


def infrastructure_retry_delay(retry_index: int) -> float:
    return float(min(2**retry_index, 10))
