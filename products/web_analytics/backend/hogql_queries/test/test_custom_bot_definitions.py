import pytest
from posthog.test.base import BaseTest, ClickhouseTestMixin

from parameterized import parameterized

from posthog.schema import CustomBotCondition, CustomBotField, CustomBotMatcher, CustomBotRule

from posthog.schema_enums import FilterLogicalOperator

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
from products.web_analytics.backend.hogql_queries.custom_bot_definitions import (
    MAX_CONDITIONS_PER_RULE,
    MAX_CUSTOM_BOT_DEFINITIONS,
    MAX_PATTERN_LENGTH,
    TRAFFIC_TYPE_BY_CATEGORY,
    CidrGroup,
    CompositeGroup,
    PatternGroup,
    assert_patterns_compile,
    compile_cidr,
    compile_definitions,
    compile_pattern,
    compiled_patterns,
    upcast_rules,
    validate_rule,
)


def condition(**kwargs) -> CustomBotCondition:
    return CustomBotCondition(
        **{
            "id": "1",
            "key": CustomBotField.FIELD_RAW_USER_AGENT,
            "pattern": "AcmeBot",
            "matcher": CustomBotMatcher.CONTAINS,
            **kwargs,
        }
    )


def rule(
    *, items: list[CustomBotCondition] | None = None, combiner=FilterLogicalOperator.AND_, **kwargs
) -> CustomBotRule:
    condition_overrides = {key: kwargs.pop(key) for key in ("key", "pattern", "matcher") if key in kwargs}
    return CustomBotRule(
        **{
            "id": "1",
            "name": "Acme scraper",
            "combiner": combiner,
            "items": items if items is not None else [condition(**condition_overrides)],
            **kwargs,
        }
    )


def cidr_rule(**kwargs) -> CustomBotRule:
    return rule(
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
            # Unanchored, "800" would also flag every 1800-wide screen; unescaped, "1.5" would
            # also match "125".
            ("a number", "800", "^800$"),
            ("a value with metacharacters", "1.5", r"^1\.5$"),
        ]
    )
    def test_exact_compiles_to_an_anchored_literal(self, _name: str, pattern: str, expected: str):
        assert compile_pattern(pattern, "exact") == expected

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
            ("no conditions", {"items": []}, "at least one condition"),
        ]
    )
    def test_rejects_unusable_rules(self, _name: str, overrides: dict, expected_message: str):
        with pytest.raises(ValueError, match=expected_message):
            validate_rule(rule(**overrides))

    def test_rejects_a_rule_with_too_many_conditions(self):
        # Every condition is a read added to every query that selects a classification field.
        overloaded = rule(items=[condition(id=str(i)) for i in range(MAX_CONDITIONS_PER_RULE + 1)])

        with pytest.raises(ValueError, match="at most"):
            validate_rule(overloaded)

    @parameterized.expand(
        [
            ("plain substring", {"pattern": "AcmeBot"}),
            ("substring with metacharacters", {"pattern": "Acme (bot) v1.0"}),
            ("anchored regex", {"pattern": "^AcmeBot/[0-9]+$", "matcher": CustomBotMatcher.REGEX}),
            ("a non-default property", {"key": CustomBotField.FIELD_LIB, "pattern": "posthog-python"}),
            ("a numeric property", {"key": CustomBotField.FIELD_SCREEN_WIDTH, "pattern": "800"}),
            (
                "equality on a numeric property",
                {"key": CustomBotField.FIELD_SCREEN_WIDTH, "pattern": "800", "matcher": CustomBotMatcher.EXACT},
            ),
            ("browser language", {"key": CustomBotField.FIELD_BROWSER_LANGUAGE, "pattern": "@posix"}),
        ]
    )
    def test_accepts_usable_rules(self, _name: str, overrides: dict):
        validate_rule(rule(**overrides))

    def test_accepts_a_multi_condition_rule(self):
        validate_rule(
            rule(
                items=[
                    condition(
                        id="w", key=CustomBotField.FIELD_SCREEN_WIDTH, matcher=CustomBotMatcher.EXACT, pattern="800"
                    ),
                    condition(
                        id="h", key=CustomBotField.FIELD_SCREEN_HEIGHT, matcher=CustomBotMatcher.EXACT, pattern="600"
                    ),
                ]
            )
        )

    @parameterized.expand(
        [
            ("single address", "192.0.2.7"),
            ("v4 range", "192.0.2.0/24"),
            ("v6 range", "2001:db8::/32"),
            ("host bits set", "192.0.2.7/24"),
        ]
    )
    def test_accepts_usable_ip_ranges(self, _name: str, pattern: str):
        validate_rule(cidr_rule(pattern=pattern))

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
            validate_rule(cidr_rule(pattern=pattern))

    def test_rejects_a_range_on_a_property_that_is_not_an_ip(self):
        # Comparing a user agent to a network range can never match, so it is a mistake worth
        # naming rather than a rule that silently does nothing.
        with pytest.raises(ValueError, match="IP ranges only work with"):
            validate_rule(rule(matcher=CustomBotMatcher.CIDR, pattern="192.0.2.0/24"))

    def test_rejects_a_property_outside_the_supported_set(self):
        raw = condition().model_dump()
        raw["key"] = "$some_other_property"

        with pytest.raises(ValueError, match="Cannot match on property"):
            validate_rule(rule(items=[CustomBotCondition.model_construct(**raw)]))


class TestUpcastRules:
    def test_reads_the_flat_shape_as_a_one_condition_rule(self):
        # Rules saved before conditions existed keep this shape in team.modifiers; they have to
        # keep classifying without a migration.
        upcast = upcast_rules(
            [{"id": "1", "name": "Acme", "key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot"}]
        )

        assert [(r.name, r.combiner, len(r.items)) for r in upcast] == [("Acme", FilterLogicalOperator.AND_, 1)]
        assert upcast[0].items[0].pattern == "AcmeBot"

    def test_keeps_the_current_shape_and_drops_what_does_not_parse(self):
        current = rule().model_dump(exclude_none=True)

        upcast = upcast_rules([current, "garbage", {"pattern": "no key"}, {"items": "not-a-list"}])

        assert [r.name for r in upcast] == ["Acme scraper"]

    def test_strict_raises_instead_of_dropping(self):
        # On the save paths a silently dropped rule reads as saved; the error has to surface.
        with pytest.raises(ValueError, match="Invalid bot rule"):
            upcast_rules([{"pattern": "no key"}], strict=True)


class TestCompileDefinitions:
    def test_unusable_rules_are_dropped_not_raised(self):
        # A rule that got past validation (saved before a rule tightened, or written straight
        # to the API) must not break every query that reads $virt_is_bot for the project.
        groups = compile_definitions(
            [
                rule(id="1", pattern="Acme(?=Bot)", matcher=CustomBotMatcher.REGEX),
                rule(id="2", name="Good bot", pattern="GoodBot"),
            ]
        )

        assert [bot.name for group in groups if isinstance(group, PatternGroup) for bot in group.definitions] == [
            "Good bot"
        ]

    def test_rules_beyond_the_cap_are_dropped(self):
        groups = compile_definitions([rule(id=str(i), name=f"Bot {i}") for i in range(MAX_CUSTOM_BOT_DEFINITIONS + 10)])

        assert sum(len(group.definitions) for group in groups if isinstance(group, PatternGroup)) == (
            MAX_CUSTOM_BOT_DEFINITIONS
        )

    def test_rules_on_the_same_property_share_one_group(self):
        # Each group is one pass over the property at query time, so two user agent rules must not
        # become two passes.
        groups = compile_definitions([rule(id="1", name="One", pattern="One"), rule(id="2", name="Two", pattern="Two")])

        assert len(groups) == 1
        assert isinstance(groups[0], PatternGroup)
        assert groups[0].patterns == ["(?i)One", "(?i)Two"]

    def test_groups_come_back_in_the_order_their_first_rule_appears(self):
        # Groups are checked in this order, so it decides which rule names an event that two of
        # them match.
        groups = compile_definitions(
            [
                rule(id="1", name="By host", key=CustomBotField.FIELD_HOST, pattern="scraper.example.com"),
                cidr_rule(id="2", name="By IP"),
                rule(id="3", name="By user agent", pattern="AcmeBot"),
            ]
        )

        assert [group.key for group in groups if not isinstance(group, CompositeGroup)] == [
            CustomBotField.FIELD_HOST.value,
            CustomBotField.FIELD_IP.value,
            CustomBotField.FIELD_RAW_USER_AGENT.value,
        ]

    def test_a_property_matched_two_ways_gets_a_group_each(self):
        # A range check and a pattern check are different expressions, so they cannot share a pass.
        groups = compile_definitions(
            [
                cidr_rule(id="1", name="Office"),
                rule(id="2", name="Loopback-ish", key=CustomBotField.FIELD_IP, pattern="127."),
            ]
        )

        assert [type(group) for group in groups] == [CidrGroup, PatternGroup]

    def test_a_multi_condition_rule_becomes_its_own_group_in_order(self):
        # A composite rule reads several properties, so it cannot share another group's hyperscan
        # pass, and it must keep its place in the precedence order between the other groups.
        groups = compile_definitions(
            [
                rule(id="1", name="First", pattern="First"),
                rule(
                    id="2",
                    name="Headless 800x600",
                    items=[
                        condition(
                            id="w", key=CustomBotField.FIELD_SCREEN_WIDTH, matcher=CustomBotMatcher.EXACT, pattern="800"
                        ),
                        condition(
                            id="h",
                            key=CustomBotField.FIELD_SCREEN_HEIGHT,
                            matcher=CustomBotMatcher.EXACT,
                            pattern="600",
                        ),
                    ],
                ),
                rule(id="3", name="Last", key=CustomBotField.FIELD_HOST, pattern="scraper.example.com"),
            ]
        )

        assert [type(group) for group in groups] == [PatternGroup, CompositeGroup, PatternGroup]
        composite = groups[1]
        assert isinstance(composite, CompositeGroup)
        assert composite.combiner == "AND"
        assert composite.definition.name == "Headless 800x600"

    def test_category_drives_traffic_type(self):
        groups = compile_definitions([rule(category="ai_crawler")])

        assert isinstance(groups[0], PatternGroup)
        bot = groups[0].definitions[0]
        assert bot.category == "ai_crawler"
        assert bot.traffic_type == "AI Agent"

    def test_defaults_to_the_custom_category(self):
        groups = compile_definitions([rule()])

        assert isinstance(groups[0], PatternGroup)
        bot = groups[0].definitions[0]
        assert bot.category == "custom"
        assert bot.traffic_type == "Bot"

    def test_compiled_patterns_skips_ip_ranges_but_covers_composite_conditions(self):
        # The save-time check hands these to hyperscan, which cannot compile a network range. A
        # composite rule's pattern conditions run through hyperscan too, so missing them here would
        # let an uncompilable pattern save and then break every classification query.
        patterns = compiled_patterns(
            [
                rule(id="1"),
                cidr_rule(id="2"),
                rule(
                    id="3",
                    name="Composite",
                    items=[
                        condition(
                            id="w", key=CustomBotField.FIELD_SCREEN_WIDTH, matcher=CustomBotMatcher.EXACT, pattern="800"
                        ),
                        condition(
                            id="ip", key=CustomBotField.FIELD_IP, matcher=CustomBotMatcher.CIDR, pattern="192.0.2.0/24"
                        ),
                    ],
                ),
            ]
        )

        assert patterns == ["(?i)AcmeBot", "^800$"]


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
