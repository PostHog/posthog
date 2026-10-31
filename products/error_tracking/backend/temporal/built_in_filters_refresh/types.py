import dataclasses


@dataclasses.dataclass(frozen=True)
class BuiltInFiltersRefreshInputs:
    batch_size: int = 500


@dataclasses.dataclass(frozen=True)
class BuiltInFiltersRefreshResult:
    rules_refreshed: int
    rules_failed: int
