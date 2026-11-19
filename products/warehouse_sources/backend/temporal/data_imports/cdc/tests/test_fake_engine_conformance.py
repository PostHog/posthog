from products.warehouse_sources.backend.temporal.data_imports.cdc.tests.conformance_kit import (
    ConformanceEngine,
    SourceDatabase,
)
from products.warehouse_sources.backend.temporal.data_imports.cdc.tests.conformance_suite import CDCConformanceSuite
from products.warehouse_sources.backend.temporal.data_imports.cdc.tests.fake_engine import FakeEngine


class TestFakeEngineConformance(CDCConformanceSuite):
    def make_engine(self, db: SourceDatabase) -> ConformanceEngine:
        return FakeEngine(db)
