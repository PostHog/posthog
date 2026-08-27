import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import CustomBotDefinition, CustomBotField, CustomBotMatcher

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
from products.web_analytics.backend.hogql_queries.custom_bot_definitions import (
    MAX_CUSTOM_BOT_DEFINITIONS,
    MAX_PATTERN_LENGTH,
    TRAFFIC_TYPE_BY_CATEGORY,
    CidrGroup,
    PatternGroup,
    assert_patterns_compile,
    compile_cidr,
    compile_definitions,
    compile_pattern,
    compiled_patterns,
    validate_definition,
)


def definition(**kwargs) -> CustomBotDefinition:
    return CustomBotDefinition(
        **{
            "id": "1",
            "name": "Acme scraper",
            "key": CustomBotField.FIELD_RAW_USER_AGENT,
            "pattern": "AcmeBot",
            "matcher": CustomBotMatcher.CONTAINS,
            **kwargs,
        }
    )


def cidr_definition(**kwargs) -> CustomBotDefinition:
    return definition(
        **{"key": CustomBotField.FIELD_IP, "matcher": CustomBotMatcher.CIDR, "pattern": "192.0.2.0/24", **kwargs}
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

    @parameterized.expand(
        [
            # The IP matcher compares in IPv6 space, so an IPv4 range shifts by 96 bits and its
            # address becomes IPv4-mapped. Comparing a /24 as-is would match nothing.
            ("192.0.2.0/24", (120, "::ffff:192.0.2.0")),
            ("192.0.2.7", (128, "::ffff:192.0.2.7")),
            # Host bits set: read as the network rather than rejected.
            ("192.0.2.7/24", (120, "::ffff:192.0.2.0")),
            ("2001:db8::/32", (32, "2001:db8::")),
        ]
    )
    def test_cidr_compiles_into_ipv6_space(self, pattern: str, expected: tuple[int, str]):
        assert compile_cidr(pattern) == expected


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
            ("a non-default property", {"key": CustomBotField.FIELD_LIB, "pattern": "posthog-python"}),
        ]
    )
    def test_accepts_usable_definitions(self, _name: str, overrides: dict):
        validate_definition(definition(**overrides))

    @parameterized.expand(
        [
            ("single address", "192.0.2.7"),
            ("v4 range", "192.0.2.0/24"),
            ("v6 range", "2001:db8::/32"),
            ("host bits set", "192.0.2.7/24"),
        ]
    )
    def test_accepts_usable_ip_ranges(self, _name: str, pattern: str):
        validate_definition(cidr_definition(pattern=pattern))

    @parameterized.expand(
        [
            ("not an address", "not-an-ip"),
            ("prefix too long", "192.0.2.0/33"),
            ("empty", "   "),
            # Python's ip_network keeps a zone identifier that ClickHouse toIPv6 later rejects, so a
            # saved rule would break every query reading a bot field. Reject it at validation.
            ("zone-scoped ipv6", "fe80::1%eth0"),
        ]
    )
    def test_rejects_unusable_ip_ranges(self, _name: str, pattern: str):
        with pytest.raises(ValueError):
            validate_definition(cidr_definition(pattern=pattern))

    def test_rejects_a_range_on_a_property_that_is_not_an_ip(self):
        # Comparing a user agent to a network range can never match, so it is a mistake worth
        # naming rather than a rule that silently does nothing.
        with pytest.raises(ValueError, match="IP ranges only work with"):
            validate_definition(definition(matcher=CustomBotMatcher.CIDR, pattern="192.0.2.0/24"))

    def test_rejects_a_property_outside_the_supported_set(self):
        raw = definition().model_dump()
        raw["key"] = "$some_other_property"

        with pytest.raises(ValueError, match="Cannot match on property"):
            validate_definition(CustomBotDefinition.model_construct(**raw))


class TestCompileDefinitions:
    def test_unusable_definitions_are_dropped_not_raised(self):
        # A definition that got past validation (saved before a rule tightened, or written straight
        # to the API) must not break every query that reads $virt_is_bot for the project.
        groups = compile_definitions(
            [
                definition(id="1", pattern="Acme(?=Bot)", matcher=CustomBotMatcher.REGEX),
                definition(id="2", name="Good bot", pattern="GoodBot"),
            ]
        )

        assert [bot.name for group in groups for bot in group.definitions] == ["Good bot"]

    def test_definitions_beyond_the_cap_are_dropped(self):
        groups = compile_definitions(
            [definition(id=str(i), name=f"Bot {i}") for i in range(MAX_CUSTOM_BOT_DEFINITIONS + 10)]
        )

        assert sum(len(group.definitions) for group in groups) == MAX_CUSTOM_BOT_DEFINITIONS

    def test_rules_on_the_same_property_share_one_group(self):
        # Each group is one pass over the property at query time, so two user agent rules must not
        # become two passes.
        groups = compile_definitions(
            [definition(id="1", name="One", pattern="One"), definition(id="2", name="Two", pattern="Two")]
        )

        assert len(groups) == 1
        assert isinstance(groups[0], PatternGroup)
        assert groups[0].patterns == ["(?i)One", "(?i)Two"]

    def test_groups_come_back_in_the_order_their_first_rule_appears(self):
        # Groups are checked in this order, so it decides which rule names an event that two of
        # them match.
        groups = compile_definitions(
            [
                definition(id="1", name="By host", key=CustomBotField.FIELD_HOST, pattern="scraper.example.com"),
                cidr_definition(id="2", name="By IP"),
                definition(id="3", name="By user agent", pattern="AcmeBot"),
            ]
        )

        assert [group.key for group in groups] == [
            CustomBotField.FIELD_HOST.value,
            CustomBotField.FIELD_IP.value,
            CustomBotField.FIELD_RAW_USER_AGENT.value,
        ]

    def test_a_property_matched_two_ways_gets_a_group_each(self):
        # A range check and a pattern check are different expressions, so they cannot share a pass.
        groups = compile_definitions(
            [
                cidr_definition(id="1", name="Office"),
                definition(id="2", name="Loopback-ish", key=CustomBotField.FIELD_IP, pattern="127."),
            ]
        )

        assert [type(group) for group in groups] == [CidrGroup, PatternGroup]

    def test_category_drives_traffic_type(self):
        groups = compile_definitions([definition(category="ai_crawler")])

        bot = groups[0].definitions[0]
        assert bot.category == "ai_crawler"
        assert bot.traffic_type == "AI Agent"

    def test_defaults_to_the_custom_category(self):
        bot = compile_definitions([definition()])[0].definitions[0]

        assert bot.category == "custom"
        assert bot.traffic_type == "Bot"

    def test_compiled_patterns_skips_ip_ranges(self):
        # The save-time check hands these to hyperscan, which cannot compile a network range.
        patterns = compiled_patterns([definition(id="1"), cidr_definition(id="2")])

        assert patterns == ["(?i)AcmeBot"]


class TestPatternsCompile(ClickhouseTestMixin, BaseTest):
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
