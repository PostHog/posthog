from parameterized import parameterized

from products.signals.backend.temporal.types import EmitSignalInputs, signal_document_id


def _signal(**overrides) -> EmitSignalInputs:
    return EmitSignalInputs(
        **{
            "team_id": 2,
            "source_product": "engineering_analytics",
            "source_type": "ci_flaky_check",
            "source_id": "PostHog/posthog:CI:warehouse-sources:2026-07-20:flaky",
            "description": "CI job 'warehouse-sources' in workflow 'CI' is flaky",
            **overrides,
        }
    )


class TestSignalDocumentId:
    def test_reprocessing_one_signal_reuses_its_document(self):
        # document_id is what every signal read groups on. A random id per emission made a replayed or
        # retried emission a second inbox item for a condition already reported.
        assert signal_document_id(_signal()) == signal_document_id(_signal())

    def test_weight_alone_does_not_fork_the_document(self):
        # Weight is scoring, not identity — the pipeline may rescore the same emission.
        assert signal_document_id(_signal(weight=1.0)) == signal_document_id(_signal())

    @parameterized.expand(
        [
            ("team", {"team_id": 3}),
            ("source_product", {"source_product": "error_tracking"}),
            ("source_type", {"source_type": "ci_broken_default_branch"}),
            ("source_id", {"source_id": "PostHog/posthog:CI:storybook:2026-07-20:flaky"}),
            # Sources like error tracking (issue reopened) and log alerts (alert re-fired) reuse one
            # source_id across genuinely distinct occurrences, differing only in their evidence text.
            # Keying on the tuple alone would silently overwrite the earlier occurrence.
            ("description", {"description": "CI job 'warehouse-sources' recovered on a rerun again"}),
        ]
    )
    def test_distinct_signals_get_distinct_documents(self, _name, overrides):
        assert signal_document_id(_signal(**overrides)) != signal_document_id(_signal())

    @parameterized.expand([("colon", ":"), ("pipe", "|")])
    def test_a_delimiter_inside_a_component_cannot_forge_another_tuple(self, _name, delimiter):
        # Every delimiter candidate is legal inside source_type and source_id, so a plain join lets
        # (type="a:b", id="c") and (type="a", id="b:c") share a document and overwrite each other.
        left = _signal(source_type=f"a{delimiter}b", source_id="c")
        right = _signal(source_type="a", source_id=f"b{delimiter}c")
        assert signal_document_id(left) != signal_document_id(right)

    def test_blank_source_id_stays_unique_per_emission(self):
        # A blank source_id identifies nothing, so keying on it would collapse every such signal in a
        # team onto one document.
        assert signal_document_id(_signal(source_id="")) != signal_document_id(_signal(source_id=""))
