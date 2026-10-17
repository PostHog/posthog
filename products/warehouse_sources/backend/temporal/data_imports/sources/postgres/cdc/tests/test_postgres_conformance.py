from products.warehouse_sources.backend.temporal.data_imports.cdc.tests.conformance_kit import (
    ConformanceEngine,
    SourceDatabase,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.tests.conformance_suite import CDCConformanceSuite
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.tests.conformance_engine import (
    SimulatedPostgres,
)


class TestPostgresConformance(CDCConformanceSuite):
    def make_engine(self, db: SourceDatabase) -> ConformanceEngine:
        return SimulatedPostgres(db)
