from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.external_product_hooks import (
    saved_query_binding,
    schema_binding,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.core import person_property_paths as paths

_ID = "0198f2b1-0000-7000-8000-000000000001"


class TestBindingPathSegment:
    def test_schema_segment_is_the_bare_id(self):
        # Live staged folders and dedup snapshots were written under the bare schema id. Prefixing it
        # would orphan every one of them, and each source would re-send its whole table on the next run.
        assert paths.binding_path_segment(schema_binding(_ID)) == _ID

    def test_saved_query_segment_is_prefixed(self):
        assert paths.binding_path_segment(saved_query_binding(_ID)) == f"model_{_ID}"

    def test_kinds_sharing_an_id_do_not_collide(self):
        schema, view = schema_binding(_ID), saved_query_binding(_ID)
        assert paths.binding_staged_prefix(1, schema) != paths.binding_staged_prefix(1, view)
        assert paths.snapshot_prefix(1, schema, "src") != paths.snapshot_prefix(1, view, "src")

    @parameterized.expand(
        [
            ("staged", lambda binding: paths.job_staged_prefix(1, binding, "job-1")),
            ("snapshot", lambda binding: paths.snapshot_prefix(1, binding, "src")),
        ]
    )
    def test_job_and_snapshot_prefixes_carry_the_segment(self, _name, build):
        assert paths.binding_path_segment(saved_query_binding(_ID)) in build(saved_query_binding(_ID))

    def test_job_prefix_nests_under_the_binding_prefix(self):
        # The sink sweeps abandoned sibling jobs by listing the binding prefix, so a job folder has to
        # sit directly under it.
        binding = saved_query_binding(_ID)
        assert paths.job_staged_prefix(1, binding, "job-1") == f"{paths.binding_staged_prefix(1, binding)}/job-1"
