import pytest

from parameterized import parameterized

from posthog.schema import CustomBotDefinition, CustomBotMatcher

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
from products.web_analytics.backend.hogql_queries.custom_bot_definitions import (
    MAX_CUSTOM_BOT_DEFINITIONS,
    MAX_PATTERN_LENGTH,
    TRAFFIC_TYPE_BY_CATEGORY,
    assert_patterns_compile,
    compile_pattern,
    to_bot_definitions,
    validate_definition,
)


def definition(**kwargs) -> CustomBotDefinition:
    return CustomBotDefinition(
        **{
            "id": "1",
            "name": "Acme scraper",
            "pattern": "AcmeBot",
            "matcher": CustomBotMatcher.CONTAINS,
            **kwargs,
        }
    )


class TestPatternCompilation:
    @parameterized.expand(
        [
            ("Acme (bot)", r"(?i)Acme \(bot\)"),
            ("v1.0", r"(?i)v1\.0"),
            ("a+b", r"(?i)a\+b"),
        ]
    )
    def test_contains_escapes_regex_metacharacters(self, pattern: str, expected: str):
        # An unescaped "(" would either change what the pattern matches or make hyperscan reject it.
        assert compile_pattern(pattern, "contains") == expected

    def test_regex_is_passed_through(self):
        assert compile_pattern("AcmeBot/[0-9]+", "regex") == "AcmeBot/[0-9]+"


class TestValidation:
    @parameterized.expand(
        [
            ("empty", {"pattern": ""}, "Pattern cannot be empty"),
            ("whitespace", {"pattern": "   "}, "Pattern cannot be empty"),
            ("too long", {"pattern": "a" * (MAX_PATTERN_LENGTH + 1)}, "cannot be longer"),
            ("no name", {"name": ""}, "Bot name cannot be empty"),
            (
                "lookahead",
                {"pattern": "Acme(?=Bot)", "matcher": CustomBotMatcher.REGEX},
                "lookahead",
            ),
            (
                "lookbehind",
                {"pattern": "(?<=Acme)Bot", "matcher": CustomBotMatcher.REGEX},
                "lookbehind",
            ),
            (
                "backreference",
                {"pattern": r"(Acme)\1", "matcher": CustomBotMatcher.REGEX},
                "backreference",
            ),
            (
                "invalid regex",
                {"pattern": "Acme(", "matcher": CustomBotMatcher.REGEX},
                "not a valid regular expression",
            ),
            ("unknown category", {"category": "not_a_category"}, "Unknown category"),
        ]
    )
    def test_rejects_unusable_definitions(self, _name: str, overrides: dict, expected_message: str):
        with pytest.raises(ValueError, match=expected_message):
            validate_definition(definition(**overrides))

    @parameterized.expand(
        [
            ("plain substring", {"pattern": "AcmeBot"}),
            ("substring with metacharacters", {"pattern": "Acme (bot) v1.0"}),
            ("anchored regex", {"pattern": "^AcmeBot/[0-9]+$", "matcher": CustomBotMatcher.REGEX}),
        ]
    )
    def test_accepts_usable_definitions(self, _name: str, overrides: dict):
        validate_definition(definition(**overrides))


class TestToBotDefinitions:
    def test_unusable_definitions_are_dropped_not_raised(self):
        # A pattern that got past validation (saved before a rule tightened, or written straight to
        # the API) must not break every query that reads $virt_is_bot for the project.
        compiled = to_bot_definitions(
            [
                definition(id="1", pattern="Acme(?=Bot)", matcher=CustomBotMatcher.REGEX),
                definition(id="2", name="Good bot", pattern="GoodBot"),
            ]
        )

        assert [bot.name for _, bot in compiled] == ["Good bot"]

    def test_definitions_beyond_the_cap_are_dropped(self):
        compiled = to_bot_definitions(
            [definition(id=str(i), name=f"Bot {i}") for i in range(MAX_CUSTOM_BOT_DEFINITIONS + 10)]
        )

        assert len(compiled) == MAX_CUSTOM_BOT_DEFINITIONS

    def test_category_drives_traffic_type(self):
        compiled = to_bot_definitions([definition(category="ai_crawler")])

        _, bot = compiled[0]
        assert bot.category == "ai_crawler"
        assert bot.traffic_type == "AI Agent"

    def test_defaults_to_the_custom_category(self):
        _, bot = to_bot_definitions([definition()])[0]

        assert bot.category == "custom"
        assert bot.traffic_type == "Bot"


@pytest.mark.clickhouse_only
class TestPatternsCompile:
    @parameterized.expand(
        [
            # Python's re accepts a huge bounded repeat and a POSIX class it does not know; ClickHouse
            # rejects both. Without this check they would save fine and then break every query that
            # reads $virt_is_bot for the project.
            ("expensive bounded repeat", "a{0,100000}", "too slow"),
            ("unknown POSIX class", "[[:foo:]]", "not supported"),
        ]
    )
    def test_rejects_patterns_clickhouse_cannot_run(self, _name: str, pattern: str, expected_message: str):
        with pytest.raises(ValueError, match=expected_message):
            assert_patterns_compile([pattern])

    def test_accepts_patterns_clickhouse_can_run(self):
        assert_patterns_compile(["(?i)AcmeBot", "AcmeBot/[0-9]+", "^$"])


class TestCategoryCoverage:
    def test_every_built_in_category_has_a_traffic_type(self):
        # A category added to BOT_DEFINITIONS without an entry here would silently report "Bot" for
        # a project's own bots in that category.
        missing = {bot.category for bot in BOT_DEFINITIONS.values()} - set(TRAFFIC_TYPE_BY_CATEGORY)

        assert missing == set()
