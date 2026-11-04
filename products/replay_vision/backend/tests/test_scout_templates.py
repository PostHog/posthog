import re

from django.test import SimpleTestCase

from parameterized import parameterized

from products.replay_vision.backend.scout_templates import (
    SCOUT_DISPLAY_NAME_MAX_LENGTH,
    ScoutTemplate,
    ScoutTemplateKey,
    scout_templates_for,
    template_key_from_skill_name,
)

SCANNER_ID = "0198b7c4-1111-2222-3333-444455556666"
# ALL-CAPS slots are what an author must fill in; the create form blocks saving while any remain.
PLACEHOLDER = re.compile(r"<[A-Z][^<>]*>")


def _template(scanner_type: str | None, key: ScoutTemplateKey, scanner_name: str = "Rage clicks") -> ScoutTemplate:
    return next(t for t in scout_templates_for(SCANNER_ID, scanner_type, scanner_name) if t.key == key)


class TestScoutTemplates(SimpleTestCase):
    @parameterized.expand([("monitor",), ("classifier",), ("scorer",), ("summarizer",), ("experiment",)])
    def test_every_template_is_scoped_to_the_scanner_and_ready_to_save(self, scanner_type: str) -> None:
        templates = scout_templates_for(SCANNER_ID, scanner_type, "Rage clicks")
        keys = [t.key for t in templates]
        assert len(set(keys)) == len(keys)
        for template in templates:
            # vision-scanners-get takes `id`; pairing it with scanner_id fails the first move of every run.
            assert f"`vision-scanners-get` with id `{SCANNER_ID}`" in template.body
            # Daily or Mondays: the two shapes the schedule form can edit without calling it custom.
            assert re.fullmatch(r"\d+ \d+ \* \* (\*|1)", template.cron)
            assert template.default_name.strip()
            has_slots = bool(PLACEHOLDER.search(template.body))
            # The scratch body ships the judgment blank so it can't be saved unedited; the others must save as-is.
            assert has_slots == (template.key == ScoutTemplateKey.SCRATCH), template.key

    @parameterized.expand(
        [
            ("monitor", ["daily-digest", "root-cause", "trend-watch", "new-issues", "scratch"]),
            # A summarizer has no outcome to explain and no metric to trend.
            ("summarizer", ["daily-digest", "weekly-themes", "new-issues", "scratch"]),
            ("experiment", ["variant-analysis", "daily-digest", "trend-watch", "new-issues", "scratch"]),
            # A scanner of an unknown type still gets a usable set rather than nothing.
            (None, ["daily-digest", "root-cause", "trend-watch", "new-issues", "scratch"]),
        ]
    )
    def test_offers_only_the_templates_that_fit_the_scanner_type(self, scanner_type: str | None, keys: list) -> None:
        assert [t.key for t in scout_templates_for(SCANNER_ID, scanner_type, "Rage clicks")] == keys

    @parameterized.expand(
        [
            ("monitor", "scanner_output_verdict = 'yes'"),
            ("scorer", "scanner_output_score"),
            ("classifier", "scanner_output_tags"),
        ]
    )
    def test_root_cause_explains_the_bucket_from_the_scanner_reasoning_first(
        self, scanner_type: str, bucket: str
    ) -> None:
        body = _template(scanner_type, ScoutTemplateKey.ROOT_CAUSE).body
        assert bucket in body
        # The reasoning comes from the recording itself; event data may only corroborate it.
        assert body.index("scanner_output_reasoning") < body.index("`events`")

    @parameterized.expand(
        [
            ("monitor", "verdict mix", "scanner_output_verdict"),
            ("scorer", "scores", "scanner_output_score"),
            # A tag's raw count rises with traffic, so the classifier series must break down by tag.
            ("classifier", "category mix", "scanner_output_tags"),
            ("experiment", "themes", "uniq(properties.session_id)"),
        ]
    )
    def test_trend_watch_is_written_for_the_output_the_scanner_emits(
        self, scanner_type: str, description: str, series: str
    ) -> None:
        template = _template(scanner_type, ScoutTemplateKey.TREND_WATCH)
        assert description in template.description
        assert series in template.body

    def test_stateful_templates_keep_their_memory_keyed_on_the_scanner(self) -> None:
        # Novelty needs remembered history, keyed so the first move's search finds it again.
        new_issues = _template("monitor", ScoutTemplateKey.NEW_ISSUES).body
        assert f"{SCANNER_ID}:pattern:known-issues" in new_issues
        assert "scanner_version" in new_issues
        variant_analysis = _template("experiment", ScoutTemplateKey.VARIANT_ANALYSIS).body
        assert "scout-record-output" in variant_analysis
        assert f"{SCANNER_ID}:pattern:variant-tally" in variant_analysis

    @parameterized.expand(
        [
            ("Rage clicks on checkout", "Rage clicks on checkout daily digest"),
            # An unnamed scanner, or one with no letters or numbers, gets the bare phrase.
            ("", "Daily digest"),
            ("!!!", "Daily digest"),
            ("!!! 42", "!!! 42 daily digest"),
            # A non-Latin name is still a name.
            ("日本語", "日本語 daily digest"),
        ]
    )
    def test_default_name_leads_with_the_scanner(self, scanner_name: str, expected: str) -> None:
        assert _template("monitor", ScoutTemplateKey.DAILY_DIGEST, scanner_name).default_name == expected

    def test_default_name_fits_the_display_name_cap(self) -> None:
        # The scanner name allows 255 characters and the display name only 200.
        name = _template("monitor", ScoutTemplateKey.DAILY_DIGEST, "x" * 255).default_name
        assert len(name) == SCOUT_DISPLAY_NAME_MAX_LENGTH

    @parameterized.expand(
        [
            ("signals-scout-checkout-new-issues", ScoutTemplateKey.NEW_ISSUES),
            # A second scanner with the same name gets a collision suffix.
            ("signals-scout-checkout-root-cause-2", ScoutTemplateKey.ROOT_CAUSE),
            ("signals-scout-root-cause-checkout-daily-digest", ScoutTemplateKey.DAILY_DIGEST),
            ("signals-scout-checkout-watcher", None),
        ]
    )
    def test_reads_the_template_back_from_a_skill_name(
        self, skill_name: str, expected: ScoutTemplateKey | None
    ) -> None:
        assert template_key_from_skill_name(skill_name) == expected
