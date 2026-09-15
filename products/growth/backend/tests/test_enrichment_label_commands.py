import json
import datetime as dt
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from io import StringIO
from pathlib import Path
from typing import Any
from uuid import UUID

from posthog.test.base import BaseTest, NonAtomicBaseTest
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.utils import timezone

from parameterized import parameterized

from posthog.models.organization import Organization

from products.growth.backend.enrichment import label_batch as label_batch_module
from products.growth.backend.models import EnrichmentLabelResult, EnrichmentPromptConfig, OrganizationEnrichmentFetch

_LABEL_BATCH_MODULE = "products.growth.backend.enrichment.label_batch"
_LAB_MODULE = "products.growth.backend.enrichment.lab"

_OUTPUT_FIELDS = [
    {"key": "is_ai", "type": "boolean", "description": ""},
    {"key": "confidence", "type": "number", "description": ""},
    {"key": "reasoning", "type": "string", "description": ""},
]


def _response(content: str, prompt_tokens: int | None = None, completion_tokens: int | None = None) -> MagicMock:
    response = MagicMock()
    response.choices[0].message.content = content
    if prompt_tokens is not None and completion_tokens is not None:
        response.usage.prompt_tokens = prompt_tokens
        response.usage.completion_tokens = completion_tokens
    return response


def _good_response(prompt_tokens: int | None = None, completion_tokens: int | None = None) -> MagicMock:
    content = json.dumps({"is_ai": True, "confidence": 0.9, "reasoning": "x"})
    return _response(content, prompt_tokens, completion_tokens)


def _bad_response() -> MagicMock:
    return _response("not json at all")


def _mock_llm_client() -> MagicMock:
    client = MagicMock()
    # Command call sites chain .with_options(max_retries=0) onto get_llm_client(...); without
    # this self-reference, that call returns an unconfigured child mock and every call made
    # through it is invisible to assertions on `client`.
    client.with_options.return_value = client
    client.chat.completions.create.return_value = _good_response()
    return client


class _BatchCommandTestCase(BaseTest):
    def _config(self, **overrides: Any) -> EnrichmentPromptConfig:
        params: dict[str, Any] = {
            "name": "test_label",
            "version": "v1",
            "prompt_text": "... Email: {email}",
            "model": "gpt-5-mini",
            "input_fields": ["name"],
            "output_fields": _OUTPUT_FIELDS,
            "is_active": True,
        }
        params.update(overrides)
        return EnrichmentPromptConfig.objects.create(**params)

    def _fetch(
        self, organization: Organization | None = None, payload: dict[str, Any] | list[Any] | None = None
    ) -> OrganizationEnrichmentFetch:
        return OrganizationEnrichmentFetch.objects.create(
            organization=organization or self.organization,
            provider="harmonic",
            payload=payload if payload is not None else {"name": "Acme"},
        )


class TestGatewayRetryBudget(_BatchCommandTestCase):
    def test_batch_disables_sdk_internal_retries(self):
        # get_llm_client builds an OpenAI() client without max_retries, so the SDK's own default
        # of 2 stacks under tenacity's stop_after_attempt(3): up to 9 HTTP requests per fetch
        # instead of 3. The command must opt out of the SDK's layer so tenacity is the only one.
        self._config()
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        client.with_options.assert_called_once_with(max_retries=0)

    def test_dry_run_disables_sdk_internal_retries(self):
        self._config()
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_LAB_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_dry_run", label="test_label", sample=1)

        client.with_options.assert_called_once_with(max_retries=0)


class TestCircuitBreaker(_BatchCommandTestCase):
    def test_aborts_after_consecutive_failures_without_walking_the_whole_archive(self):
        self._config()
        for i in range(5):
            self._fetch(organization=Organization.objects.create(name=f"org-{i}"))
        client = _mock_llm_client()
        client.chat.completions.create.return_value = _bad_response()

        with (
            patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client),
            patch(f"{_LABEL_BATCH_MODULE}.capture_exception"),
        ):
            with self.assertRaises(CommandError) as ctx:
                call_command("enrichment_label_batch", label="test_label", workers=1, max_failures=2)

        assert "aborted after 2 consecutive failures" in str(ctx.exception)
        # The breaker must stop enumeration itself, not just report a bad ratio at the end.
        assert client.chat.completions.create.call_count == 2
        assert EnrichmentLabelResult.objects.count() == 0

    def test_resets_the_streak_on_any_success_so_interleaved_failures_never_trip_it(self):
        self._config()
        for i in range(4):
            self._fetch(organization=Organization.objects.create(name=f"org-{i}"))
        client = _mock_llm_client()
        client.chat.completions.create.side_effect = [
            _bad_response(),
            _good_response(),
            _bad_response(),
            _good_response(),
        ]

        with (
            patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client),
            patch(f"{_LABEL_BATCH_MODULE}.capture_exception"),
        ):
            # max_failures=2 would trip on two failures in a row; these two never land back to
            # back, so the run must complete rather than abort partway through.
            call_command("enrichment_label_batch", label="test_label", workers=1, max_failures=2)

        assert client.chat.completions.create.call_count == 4
        assert EnrichmentLabelResult.objects.count() == 2


class TestKeysetPagination(_BatchCommandTestCase):
    @parameterized.expand(
        [
            ("spans_multiple_batches_with_no_limit", None, 5),
            ("limit_bounds_attempted_orgs_across_batches", 3, 3),
        ]
    )
    def test_every_org_is_processed_exactly_once(self, _name, limit, expected_count):
        self._config()
        for i in range(5):
            self._fetch(organization=Organization.objects.create(name=f"org-{i}"))
        client = _mock_llm_client()
        options = {"label": "test_label", "workers": 1}
        if limit is not None:
            options["limit"] = limit

        with (
            patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client),
            # Forces the 5 orgs across 3 keyset pages instead of 1, so a cursor off-by-one would
            # duplicate or skip a row instead of silently passing on a single-page test.
            patch(f"{_LABEL_BATCH_MODULE}._ID_BATCH_SIZE", 2),
        ):
            call_command("enrichment_label_batch", **options)

        assert EnrichmentLabelResult.objects.count() == expected_count
        assert EnrichmentLabelResult.objects.values_list("organization_id", flat=True).distinct().count() == (
            expected_count
        )

    def test_limit_walks_past_an_already_processed_prefix_instead_of_re_enumerating_it(self):
        # --limit means "attempt at most this many non-skipped orgs", not "consider at most this
        # many candidate rows". Pushing --limit into the page query itself made a resumed run
        # against an already-processed prefix enumerate the same N skipped orgs, attempt 0, and
        # make no progress on every subsequent invocation.
        self._config()
        already_done = [Organization.objects.create(name=f"done-{i}") for i in range(3)]
        for org in already_done:
            fetch = self._fetch(organization=org)
            EnrichmentLabelResult.objects.create(
                organization=org,
                fetch=fetch,
                label_name="test_label",
                prompt_version="v1",
                prompt_hash="irrelevant",
                model="gpt-5-mini",
                output={"is_ai": True},
            )
        fresh_org = Organization.objects.create(name="fresh")
        self._fetch(organization=fresh_org)
        client = _mock_llm_client()
        out = StringIO()

        with (
            patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client),
            # Forces the 3 already-done orgs and the 1 fresh org across separate keyset pages.
            patch(f"{_LABEL_BATCH_MODULE}._ID_BATCH_SIZE", 2),
        ):
            call_command("enrichment_label_batch", label="test_label", workers=1, limit=1, stdout=out)

        assert "attempted 1" in out.getvalue()
        assert EnrichmentLabelResult.objects.filter(organization=fresh_org).exists()


class TestAdvisoryLock(_BatchCommandTestCase):
    def test_a_concurrent_run_is_rejected_before_any_spend(self):
        # pg_try_advisory_lock is session-scoped and reentrant within one session, so the lock
        # must be held on a genuinely separate DB connection to simulate a second, overlapping
        # invocation — a new thread gets its own Django connection for free.
        self._config()
        self._fetch()
        client = _mock_llm_client()
        lock_key = label_batch_module._advisory_lock_key("test_label")

        holder_ready = threading.Event()
        release_holder = threading.Event()
        holder_state: dict[str, bool] = {}

        def _hold_lock_on_another_session() -> None:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [lock_key])
                holder_state["acquired"] = cursor.fetchone()[0]
            holder_ready.set()
            release_holder.wait(timeout=5)
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_key])
            connection.close()

        holder = threading.Thread(target=_hold_lock_on_another_session)
        holder.start()
        try:
            assert holder_ready.wait(timeout=5)
            assert holder_state["acquired"] is True

            with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
                with self.assertRaises(CommandError) as ctx:
                    call_command("enrichment_label_batch", label="test_label", workers=1)
            assert (
                str(ctx.exception) == "Another enrichment_label_batch run already holds the lock for label 'test_label'"
            )
            # The unique constraint stops the duplicate row; the lock must stop the call
            # that would pay for it in the first place.
            client.chat.completions.create.assert_not_called()
        finally:
            release_holder.set()
            holder.join(timeout=5)

    def test_the_lock_key_is_stable_across_processes(self):
        assert label_batch_module._advisory_lock_key("test_label") == -8658742456223998626


class TestUnknownAccounting(_BatchCommandTestCase):
    def test_counts_a_skip_as_unknown_even_when_the_schema_has_no_boolean_field(self):
        # verdict_field_key(config) is None here since no output field is boolean-typed. The old
        # `output.get(verdict_key) == UNKNOWN` check silently no-ops in that case, and the skipped
        # row counts as succeeded instead of unknown.
        self._config(output_fields=[{"key": "summary", "type": "string", "description": ""}])
        self._fetch(payload={})
        client = _mock_llm_client()
        out = StringIO()

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1, stdout=out)

        assert "unknown 1" in out.getvalue()
        client.chat.completions.create.assert_not_called()
        result = EnrichmentLabelResult.objects.get(label_name="test_label")
        assert result.output["meta"]["skipped"]


class TestExitCodeAndSummary(_BatchCommandTestCase):
    @parameterized.expand(
        [
            ("above_the_default_threshold_does_not_fail", None, False),
            ("below_a_custom_threshold_fails", 0.9, True),
        ]
    )
    def test_exit_code_follows_success_rate_not_a_single_failure(self, _name, min_success_rate, expect_raise):
        self._config()
        for i in range(4):
            self._fetch(organization=Organization.objects.create(name=f"org-{i}"))
        client = _mock_llm_client()
        client.chat.completions.create.side_effect = [
            _bad_response(),
            _good_response(),
            _good_response(),
            _good_response(),
        ]
        options = {"label": "test_label", "workers": 1}
        if min_success_rate is not None:
            options["min_success_rate"] = min_success_rate

        with (
            patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client),
            patch(f"{_LABEL_BATCH_MODULE}.capture_exception"),
        ):
            if expect_raise:
                with self.assertRaises(CommandError):
                    call_command("enrichment_label_batch", **options)
            else:
                call_command("enrichment_label_batch", **options)

        # 3 of 4 orgs succeeded either way; only the exit code should differ.
        assert EnrichmentLabelResult.objects.count() == 3

    def test_summary_reaches_stdout_even_when_the_run_fails(self):
        # Previously the summary was only written on the success path; on failure it went out
        # only as a CommandError on stderr, so a wrapper parsing stdout got nothing on the run
        # that most needed the counts.
        self._config()
        self._fetch()
        client = _mock_llm_client()
        client.chat.completions.create.return_value = _bad_response()
        out = StringIO()

        with (
            patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client),
            patch(f"{_LABEL_BATCH_MODULE}.capture_exception"),
        ):
            with self.assertRaises(CommandError):
                call_command("enrichment_label_batch", label="test_label", workers=1, stdout=out)

        assert "attempted 1" in out.getvalue()
        assert "failures 1" in out.getvalue()

    def test_summary_accumulates_prompt_and_completion_tokens_across_the_run(self):
        self._config()
        for i in range(2):
            self._fetch(organization=Organization.objects.create(name=f"org-{i}"))
        client = _mock_llm_client()
        client.chat.completions.create.side_effect = [
            _good_response(prompt_tokens=100, completion_tokens=10),
            _good_response(prompt_tokens=250, completion_tokens=15),
        ]
        out = StringIO()

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1, stdout=out)

        assert "prompt_tokens 350" in out.getvalue()
        assert "completion_tokens 25" in out.getvalue()

    @parameterized.expand([("zero", 0), ("negative", -1)])
    def test_limit_must_be_at_least_one(self, _name, limit):
        self._config()
        with self.assertRaises(CommandError):
            call_command("enrichment_label_batch", label="test_label", limit=limit)


class TestExpectedVersionGuard(_BatchCommandTestCase):
    """--expected-version lets a caller that resolved the active version itself (the ai_enrichment
    dag) assert nothing changed it before spending - see ai_enrichment.py's module docstring."""

    def test_a_mismatched_expected_version_aborts_before_any_spend(self):
        self._config(version="v2")
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            with self.assertRaises(CommandError):
                call_command("enrichment_label_batch", label="test_label", workers=1, expected_version="v1")

        client.chat.completions.create.assert_not_called()
        assert EnrichmentLabelResult.objects.count() == 0

    def test_a_matching_expected_version_runs_normally(self):
        self._config(version="v2")
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1, expected_version="v2")

        assert EnrichmentLabelResult.objects.count() == 1

    def test_omitting_expected_version_is_unchanged_manual_cli_behavior(self):
        self._config()
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        assert EnrichmentLabelResult.objects.count() == 1


class TestWorkerConnectionErrors(NonAtomicBaseTest):
    """Non-atomic: worker threads get their own DB connections, matching the pattern in
    TestEnrichmentLabelBatchConcurrency (test_enrichment_labels.py) for the same reason."""

    def test_a_db_error_closing_stale_connections_is_captured_not_left_to_crash_the_run(self):
        # close_old_connections() used to run outside _process's try, so a failure there escaped
        # future.result() and skipped the summary/log entirely instead of counting as a failure.
        EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=_OUTPUT_FIELDS,
            is_active=True,
        )
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        client = _mock_llm_client()

        with (
            patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client),
            patch(f"{_LABEL_BATCH_MODULE}.close_old_connections", side_effect=RuntimeError("connection reset")),
            patch(f"{_LABEL_BATCH_MODULE}.capture_exception") as capture_mock,
        ):
            with self.assertRaises(CommandError):
                call_command("enrichment_label_batch", label="test_label", workers=2)

        capture_mock.assert_called_once()


class TestDryRunFixes(BaseTest):
    def _config(self) -> EnrichmentPromptConfig:
        return EnrichmentPromptConfig.objects.create(
            name="test_label",
            version="v1",
            prompt_text="... Email: {email}",
            model="gpt-5-mini",
            input_fields=["name"],
            output_fields=_OUTPUT_FIELDS,
            is_active=True,
        )

    def test_a_non_dict_payload_prints_an_error_row_instead_of_crashing_the_run(self):
        self._config()
        bad_org = Organization.objects.create(name="bad-org")
        OrganizationEnrichmentFetch.objects.create(
            organization=bad_org, provider="harmonic", payload=["not", "a", "dict"]
        )
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload={"name": "Acme"}
        )
        client = _mock_llm_client()
        out = StringIO()

        with patch(f"{_LAB_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_dry_run", label="test_label", sample=2, stdout=out)

        printed = out.getvalue()
        assert "ERROR" in printed
        assert "classified 1, unknown 0, errors 1" in printed

    def test_raises_when_every_sampled_row_errors(self):
        self._config()
        OrganizationEnrichmentFetch.objects.create(
            organization=self.organization, provider="harmonic", payload=["not", "a", "dict"]
        )
        client = _mock_llm_client()

        with patch(f"{_LAB_MODULE}.get_llm_client", return_value=client):
            with self.assertRaises(CommandError):
                call_command("enrichment_label_dry_run", label="test_label", sample=1)


class TestAiProcessingConsent(_BatchCommandTestCase):
    def test_a_declined_org_is_never_sent_to_the_llm(self):
        self._config()
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        client.chat.completions.create.assert_not_called()
        assert EnrichmentLabelResult.objects.count() == 0

    def test_no_row_is_written_so_a_later_re_approval_is_picked_up(self):
        # Storing a skip row would occupy the (org, label, version, fetch) slot and make the
        # decision permanent: re-approving would never reclassify.
        self._config()
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)
        self.organization.is_ai_data_processing_approved = True
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        assert EnrichmentLabelResult.objects.count() == 1

    def test_revoking_mid_run_is_honored_for_orgs_still_queued(self):
        # The guard reads the DB rather than the Organization loaded during enumeration, so a
        # revocation partway through a multi-hour run stops the orgs that haven't been reached.
        self._config()
        first_org = self.organization
        second_org = Organization.objects.create(name="Second")
        self._fetch(organization=first_org)
        self._fetch(organization=second_org)
        client = _mock_llm_client()

        def _revoke_after_first(*args: Any, **kwargs: Any):
            Organization.objects.filter(pk=second_org.pk).update(is_ai_data_processing_approved=False)
            return client.chat.completions.create.return_value

        client.chat.completions.create.side_effect = _revoke_after_first

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        assert client.chat.completions.create.call_count == 1
        assert EnrichmentLabelResult.objects.count() == 1

    def test_an_unset_consent_column_counts_as_not_approved(self):
        # The column is nullable; the rest of the repo treats unset as unapproved.
        self._config()
        Organization.objects.filter(pk=self.organization.pk).update(is_ai_data_processing_approved=None)
        self._fetch()
        client = _mock_llm_client()

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1)

        client.chat.completions.create.assert_not_called()

    def test_the_skip_is_counted_in_the_summary(self):
        self._config()
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self._fetch()
        client = _mock_llm_client()
        out = StringIO()

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1, stdout=out)

        assert "skipped_no_ai_consent 1" in out.getvalue()

    def test_a_declined_org_ordered_before_an_approved_one_does_not_consume_the_limit(self):
        # Regression: --limit used to count a declined org as "attempted" the moment it was
        # enumerated, before the consent check (which only ran later, at spend-time inside
        # _process). A declined org costs nothing, so with --limit 1 and a declined org sorting
        # first by organization_id, the run used to exhaust its whole budget on that one free
        # skip and never even enumerate the approved org behind it - zero verdicts, yet the
        # command still exited 0 (tried == 0 skips the "every attempted org failed" check). A
        # consent-filtered candidate count downstream can't tell that apart from a real failure.
        self._config()
        org_x = Organization.objects.create(name="x")
        org_y = Organization.objects.create(name="y")
        declined_org, approved_org = sorted([org_x, org_y], key=lambda org: str(org.id))
        declined_org.is_ai_data_processing_approved = False
        declined_org.save(update_fields=["is_ai_data_processing_approved"])
        self._fetch(organization=declined_org)
        self._fetch(organization=approved_org)
        client = _mock_llm_client()
        out = StringIO()

        with patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_batch", label="test_label", workers=1, limit=1, stdout=out)

        assert EnrichmentLabelResult.objects.filter(organization=approved_org).exists()
        assert "attempted 1" in out.getvalue()
        assert "skipped_no_ai_consent 1" in out.getvalue()
        assert "failures 0" in out.getvalue()

    def test_the_dry_run_prints_a_skip_row_rather_than_an_error(self):
        self._config()
        self.organization.is_ai_data_processing_approved = False
        self.organization.save(update_fields=["is_ai_data_processing_approved"])
        self._fetch()
        client = _mock_llm_client()
        out = StringIO()

        with patch(f"{_LAB_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_dry_run", label="test_label", sample=1, stdout=out)

        output = out.getvalue()
        assert "SKIPPED: no AI consent" in output
        assert "errors 0" in output
        client.chat.completions.create.assert_not_called()


_STORED_RESULT_FIELDS = ("label_name", "prompt_version", "prompt_hash", "model", "output", "inputs")


def _stored_results() -> dict[UUID, tuple[Any, ...]]:
    rows = EnrichmentLabelResult.objects.values_list("organization_id", *_STORED_RESULT_FIELDS)
    return {row[0]: row[1:] for row in rows}


class TestLabelBatchGolden(_BatchCommandTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.capture_exception = MagicMock()

    @contextmanager
    def _batch(self, client: MagicMock) -> Iterator[StringIO]:
        clock = MagicMock()
        clock.monotonic.side_effect = [100.0, 101.5]
        with (
            patch(f"{_LABEL_BATCH_MODULE}.get_llm_client", return_value=client),
            patch(f"{_LABEL_BATCH_MODULE}.time", clock),
            patch(f"{_LABEL_BATCH_MODULE}.capture_exception", self.capture_exception),
        ):
            yield StringIO()

    def test_a_mixed_archive_prints_the_summary_and_stores_one_row_per_attempted_org(self):
        config = self._config()
        done_org = Organization.objects.create(name="done")
        done_fetch = self._fetch(organization=done_org)
        EnrichmentLabelResult.objects.create(
            organization=done_org,
            fetch=done_fetch,
            label_name="test_label",
            prompt_version="v1",
            prompt_hash="irrelevant",
            model="gpt-5-mini",
            output={"is_ai": True},
        )
        declined_org = Organization.objects.create(name="declined", is_ai_data_processing_approved=False)
        self._fetch(organization=declined_org)
        ghost_org = Organization.objects.create(name="ghost")
        self._fetch(organization=ghost_org, payload={})
        self._fetch()
        client = _mock_llm_client()
        client.chat.completions.create.return_value = _good_response(prompt_tokens=100, completion_tokens=10)

        with self._batch(client) as out:
            call_command("enrichment_label_batch", label="test_label", workers=1, stdout=out)

        assert out.getvalue() == (
            "attempted 2, succeeded 2, skipped_existing 1, skipped_no_ai_consent 1, unknown 1, "
            "failures 0, aborted 0, prompt_tokens 100, completion_tokens 10, elapsed_seconds 1.5\n"
        )
        assert client.chat.completions.create.call_count == 1
        self.capture_exception.assert_not_called()
        assert _stored_results() == {
            done_org.id: ("test_label", "v1", "irrelevant", "gpt-5-mini", {"is_ai": True}, {}),
            ghost_org.id: (
                "test_label",
                "v1",
                config.content_hash,
                "gpt-5-mini",
                {"is_ai": "unknown", "meta": {"skipped": "missing or empty archived payload"}},
                {"signup_domain": None, "fields": {}},
            ),
            self.organization.id: (
                "test_label",
                "v1",
                config.content_hash,
                "gpt-5-mini",
                {
                    "is_ai": True,
                    "confidence": 0.9,
                    "reasoning": "x",
                    "meta": {"prompt_tokens": 100, "completion_tokens": 10},
                },
                {"signup_domain": "posthog.com", "fields": {"name": "Acme"}},
            ),
        }

    def test_the_circuit_breaker_stops_enumeration_and_raises_with_the_summary(self):
        self._config()
        orgs = sorted((Organization.objects.create(name=f"org-{i}") for i in range(3)), key=lambda org: str(org.id))
        for org in orgs:
            self._fetch(organization=org)
        client = _mock_llm_client()
        client.chat.completions.create.return_value = _bad_response()

        with self._batch(client) as out:
            with self.assertRaises(CommandError) as ctx:
                call_command("enrichment_label_batch", label="test_label", workers=1, max_failures=2, stdout=out)

        summary = (
            "attempted 2, succeeded 0, skipped_existing 0, skipped_no_ai_consent 0, unknown 0, "
            "failures 2, aborted 0, prompt_tokens 0, completion_tokens 0, elapsed_seconds 1.5"
        )
        assert out.getvalue() == f"{summary}\n"
        assert str(ctx.exception) == f"aborted after 2 consecutive failures ({summary})"
        assert client.chat.completions.create.call_count == 2
        assert [call.args[1] for call in self.capture_exception.call_args_list] == [
            {"organization_id": str(orgs[0].id), "label": "test_label", "prompt_version": "v1"},
            {"organization_id": str(orgs[1].id), "label": "test_label", "prompt_version": "v1"},
        ]
        assert _stored_results() == {}

    def test_a_run_where_every_attempted_org_failed_raises_with_the_summary(self):
        self._config()
        self._fetch()
        client = _mock_llm_client()
        client.chat.completions.create.return_value = _bad_response()

        with self._batch(client) as out:
            with self.assertRaises(CommandError) as ctx:
                call_command("enrichment_label_batch", label="test_label", workers=1, stdout=out)

        summary = (
            "attempted 1, succeeded 0, skipped_existing 0, skipped_no_ai_consent 0, unknown 0, "
            "failures 1, aborted 0, prompt_tokens 0, completion_tokens 0, elapsed_seconds 1.5"
        )
        assert out.getvalue() == f"{summary}\n"
        assert str(ctx.exception) == f"every attempted org failed ({summary})"
        assert client.chat.completions.create.call_count == 1
        assert self.capture_exception.call_count == 1
        assert _stored_results() == {}

    def test_a_success_rate_below_the_threshold_raises_after_storing_the_successes(self):
        config = self._config()
        first_org, second_org = sorted(
            (Organization.objects.create(name=f"org-{i}") for i in range(2)), key=lambda org: str(org.id)
        )
        self._fetch(organization=first_org)
        self._fetch(organization=second_org)
        client = _mock_llm_client()
        client.chat.completions.create.side_effect = [_bad_response(), _good_response()]

        with self._batch(client) as out:
            with self.assertRaises(CommandError) as ctx:
                call_command("enrichment_label_batch", label="test_label", workers=1, min_success_rate=0.9, stdout=out)

        summary = (
            "attempted 2, succeeded 1, skipped_existing 0, skipped_no_ai_consent 0, unknown 0, "
            "failures 1, aborted 0, prompt_tokens 0, completion_tokens 0, elapsed_seconds 1.5"
        )
        assert out.getvalue() == f"{summary}\n"
        assert str(ctx.exception) == f"success_rate 0.50 is below --min-success-rate 0.9 ({summary})"
        assert client.chat.completions.create.call_count == 2
        assert self.capture_exception.call_count == 1
        assert _stored_results() == {
            second_org.id: (
                "test_label",
                "v1",
                config.content_hash,
                "gpt-5-mini",
                {"is_ai": True, "confidence": 0.9, "reasoning": "x"},
                {"signup_domain": None, "fields": {"name": "Acme"}},
            ),
        }

    @parameterized.expand(
        [
            ("no_active_config", None, {}, "No active EnrichmentPromptConfig for label 'test_label'"),
            (
                "expected_version_mismatch",
                {},
                {"expected_version": "v2"},
                "label 'test_label' active version is 'v1', expected 'v2'; "
                "the active version changed after the caller resolved it, aborting",
            ),
            (
                "invalid_output_field_type",
                {"output_fields": [{"key": "is_ai", "type": "bool", "description": ""}]},
                {},
                "enrichment output field 'is_ai' has unknown type 'bool'",
            ),
            ("workers_below_one", {}, {"workers": 0}, "--workers must be at least 1"),
            ("limit_below_one", {}, {"limit": 0}, "--limit must be at least 1"),
            ("max_failures_below_one", {}, {"max_failures": 0}, "--max-failures must be at least 1"),
        ]
    )
    def test_aborts_before_spend_with_the_exact_message(self, _name, config_overrides, options, message):
        if config_overrides is not None:
            self._config(**config_overrides)
        self._fetch()
        client = _mock_llm_client()

        with self._batch(client) as out:
            with self.assertRaises(CommandError) as ctx:
                call_command("enrichment_label_batch", **{"label": "test_label", "workers": 1, **options}, stdout=out)

        assert str(ctx.exception) == message
        assert out.getvalue() == ""
        client.chat.completions.create.assert_not_called()
        assert _stored_results() == {}


class TestLabelDryRunGolden(_BatchCommandTestCase):
    _HEADER = (
        "Company                         Domain                    is_ai     confidence  "
        "reasoning                               \n"
    )

    def _fetch_minutes_ago(
        self, minutes: int, organization: Organization | None = None, payload: dict[str, Any] | None = None
    ) -> OrganizationEnrichmentFetch:
        fetch = self._fetch(organization=organization, payload=payload)
        OrganizationEnrichmentFetch.objects.filter(pk=fetch.pk).update(
            fetched_at=timezone.now() - dt.timedelta(minutes=minutes)
        )
        return fetch

    def test_a_sample_prints_one_row_per_fetch_most_recent_first(self):
        self._config()
        self._fetch_minutes_ago(1, payload={"name": "Acme Intergalactic Holdings Incorporated"})
        self._fetch_minutes_ago(2, organization=Organization.objects.create(name="Ghost Co"), payload={})
        declined_org = Organization.objects.create(name="Declined Co", is_ai_data_processing_approved=False)
        self._fetch_minutes_ago(3, organization=declined_org, payload={"name": "Declined"})
        self._fetch_minutes_ago(
            4, organization=Organization.objects.create(name="Broken Co"), payload={"name": "Broken"}
        )
        client = _mock_llm_client()
        client.chat.completions.create.side_effect = [_good_response(), RuntimeError("gateway down")]
        out = StringIO()

        with patch(f"{_LAB_MODULE}.get_llm_client", return_value=client):
            call_command("enrichment_label_dry_run", label="test_label", no_color=True, stdout=out)

        assert out.getvalue() == (
            "Prompt version: v1\n"
            + self._HEADER
            + "Acme Intergalactic Holdings I…  posthog.com               true      0.90    "
            "x                                       \n"
            "Ghost Co                        -                         unknown   -       "
            "-                                       \n"
            "Declined Co                     -                         SKIPPED: no AI consent  -       "
            "-                                       \n"
            "Broken Co                       -                         ERROR: gateway down  -       "
            "-                                       \n"
            "classified 1, unknown 1, errors 1, skipped_no_ai_consent 1\n"
        )
        assert client.chat.completions.create.call_count == 2
        assert EnrichmentLabelResult.objects.count() == 0

    def test_compare_version_appends_the_stored_prior_verdict_columns(self):
        prior_config = self._config(
            version="v0",
            is_active=False,
            output_fields=[
                {"key": "is_ai", "type": "boolean", "description": ""},
                {"key": "score", "type": "number", "description": ""},
            ],
        )
        self._config()
        prior_fetch = self._fetch_minutes_ago(1)
        EnrichmentLabelResult.objects.create(
            organization=self.organization,
            fetch=prior_fetch,
            label_name="test_label",
            prompt_version="v0",
            prompt_hash=prior_config.content_hash,
            model="gpt-5-mini",
            output={"is_ai": False, "score": 0.25},
        )
        self._fetch_minutes_ago(2, organization=Organization.objects.create(name="Other Co"), payload={"name": "Other"})
        client = _mock_llm_client()
        out = StringIO()

        with patch(f"{_LAB_MODULE}.get_llm_client", return_value=client):
            call_command(
                "enrichment_label_dry_run", label="test_label", compare_version="v0", no_color=True, stdout=out
            )

        assert out.getvalue() == (
            "Prompt version: v1\n"
            "Company                         Domain                    is_ai     confidence  "
            "reasoning                                 prev.is_ai  prev.score\n"
            "Acme                            posthog.com               true      0.90    "
            "x                                         false     0.25  \n"
            "Other                           -                         true      0.90    "
            "x                                         -         -     \n"
            "classified 2, unknown 0, errors 0, skipped_no_ai_consent 0\n"
        )
        assert client.chat.completions.create.call_count == 2

    def test_a_sample_where_every_consenting_row_errored_raises_after_printing_the_table(self):
        self._config()
        declined_org = Organization.objects.create(name="Declined Co", is_ai_data_processing_approved=False)
        self._fetch_minutes_ago(1, organization=declined_org, payload={"name": "Declined"})
        self._fetch_minutes_ago(
            2, organization=Organization.objects.create(name="Broken Co"), payload={"name": "Broken"}
        )
        client = _mock_llm_client()
        client.chat.completions.create.side_effect = RuntimeError("gateway down")
        out = StringIO()

        with patch(f"{_LAB_MODULE}.get_llm_client", return_value=client):
            with self.assertRaises(CommandError) as ctx:
                call_command("enrichment_label_dry_run", label="test_label", no_color=True, stdout=out)

        assert out.getvalue() == (
            "Prompt version: v1\n"
            + self._HEADER
            + "Declined Co                     -                         SKIPPED: no AI consent  -       "
            "-                                       \n"
            "Broken Co                       -                         ERROR: gateway down  -       "
            "-                                       \n"
            "classified 0, unknown 0, errors 1, skipped_no_ai_consent 1\n"
        )
        assert str(ctx.exception) == (
            "every sampled row errored (classified 0, unknown 0, errors 1, skipped_no_ai_consent 1)"
        )
        assert client.chat.completions.create.call_count == 1

    def test_a_prompt_file_overrides_the_prompt_in_memory_and_marks_the_version(self):
        config = self._config()
        self._fetch()
        client = _mock_llm_client()
        out = StringIO()

        with tempfile.TemporaryDirectory() as tmp:
            prompt_path = Path(tmp) / "prompt.txt"
            prompt_path.write_text("Overridden prompt for {email}")
            with patch(f"{_LAB_MODULE}.get_llm_client", return_value=client):
                call_command(
                    "enrichment_label_dry_run",
                    label="test_label",
                    prompt_file=str(prompt_path),
                    no_color=True,
                    stdout=out,
                )

        assert out.getvalue() == (
            "Prompt version: v1+file\n"
            + self._HEADER
            + "Acme                            posthog.com               true      0.90    "
            "x                                       \n"
            "classified 1, unknown 0, errors 0, skipped_no_ai_consent 0\n"
        )
        assert client.chat.completions.create.call_args.kwargs["messages"][0] == {
            "role": "system",
            "content": "Overridden prompt for posthog.com",
        }
        config.refresh_from_db()
        assert config.prompt_text == "... Email: {email}"

    @parameterized.expand(
        [
            ("no_active_config", None, {}, "No active EnrichmentPromptConfig for label 'test_label'"),
            (
                "invalid_output_field_type",
                {"output_fields": [{"key": "is_ai", "type": "bool", "description": ""}]},
                {},
                "enrichment output field 'is_ai' has unknown type 'bool'",
            ),
            ("sample_below_one", {}, {"sample": 0}, "--sample must be at least 1"),
            (
                "missing_prompt_file",
                {},
                {"prompt_file": "/nonexistent/enrichment_prompt.txt"},
                "Could not read --prompt-file /nonexistent/enrichment_prompt.txt: "
                "[Errno 2] No such file or directory: '/nonexistent/enrichment_prompt.txt'",
            ),
            (
                "missing_compare_version",
                {},
                {"compare_version": "v9"},
                "No config 'v9' for label 'test_label' to compare against",
            ),
        ]
    )
    def test_aborts_before_spend_with_the_exact_message(self, _name, config_overrides, options, message):
        if config_overrides is not None:
            self._config(**config_overrides)
        self._fetch()
        client = _mock_llm_client()
        out = StringIO()

        with patch(f"{_LAB_MODULE}.get_llm_client", return_value=client):
            with self.assertRaises(CommandError) as ctx:
                call_command("enrichment_label_dry_run", label="test_label", stdout=out, **options)

        assert str(ctx.exception) == message
        assert out.getvalue() == ""
        client.chat.completions.create.assert_not_called()
