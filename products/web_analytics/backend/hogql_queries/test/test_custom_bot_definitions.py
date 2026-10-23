import pytest
from posthog.test.base import ClickhouseTestMixin

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.schema import CustomBotCondition, CustomBotField, CustomBotMatcher, CustomBotRule

from posthog.hogql import ast
from posthog.hogql.functions.traffic_type import _composite_branch

from posthog.schema_enums import FilterLogicalOperator

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
from products.web_analytics.backend.hogql_queries.custom_bot_definitions import (
    MAX_CONDITIONS_PER_RULE,
    MAX_CUSTOM_BOT_DEFINITIONS,
    MAX_IP_RANGES_PER_CONDITION,
    MAX_PATTERN_LENGTH,
    MAX_TOTAL_CONDITIONS,
    MAX_TOTAL_IP_RANGES,
    TRAFFIC_TYPE_BY_CATEGORY,
    CidrCondition,
    CidrGroup,
    CompositeGroup,
    PatternGroup,
    assert_patterns_compile,
    compile_cidr,
    compile_definitions,
    compile_pattern,
    compiled_patterns,
    ip_range_count,
    parse_rules,
    validate_rule,
    validate_rule_set,
)


def condition(**kwargs) -> CustomBotCondition:
    return CustomBotCondition(
        **{
            "id": "c1",
            "key": CustomBotField.FIELD_RAW_USER_AGENT,
            "pattern": "AcmeBot",
            "matcher": CustomBotMatcher.CONTAINS,
            **kwargs,
        }
    )


def rule(
    *, items: list[CustomBotCondition] | None = None, combiner=FilterLogicalOperator.AND_, **kwargs
) -> CustomBotRule:
    condition_overrides = {key: kwargs.pop(key) for key in ("key", "pattern", "patterns", "matcher") if key in kwargs}
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
        **{
            "key": CustomBotField.FIELD_IP,
            "matcher": CustomBotMatcher.CIDR,
            "pattern": None,
            "patterns": ["192.0.2.0/24"],
            **kwargs,
        }
    )


def separate_addresses(count: int, start: int = 0) -> list[str]:
    return [f"10.{n // 200}.{n % 200}.1" for n in range(start, start + count)]


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
            (("192.0.2.0/24",), ((120, ("::ffff:192.0.2.0",)),)),
            (("192.0.2.7",), ((128, ("::ffff:192.0.2.7",)),)),
            # Host bits set: read as the network rather than rejected.
            (("192.0.2.7/24",), ((120, ("::ffff:192.0.2.0",)),)),
            (("2001:db8::/32",), ((32, ("2001:db8::",)),)),
            (("192.0.2.0/24", "2001:db8::/32"), ((32, ("2001:db8::",)), (120, ("::ffff:192.0.2.0",)))),
            (("192.0.2.0/25", "192.0.2.128/25"), ((120, ("::ffff:192.0.2.0",)),)),
            (
                ("192.0.2.10-192.0.2.40",),
                (
                    (124, ("::ffff:192.0.2.16",)),
                    (125, ("::ffff:192.0.2.32",)),
                    (126, ("::ffff:192.0.2.12",)),
                    (127, ("::ffff:192.0.2.10",)),
                    (128, ("::ffff:192.0.2.40",)),
                ),
            ),
            (("192.0.2.0/24", "192.0.2.10 - 192.0.2.40"), ((120, ("::ffff:192.0.2.0",)),)),
        ]
    )
    def test_cidr_compiles_into_ipv6_space(self, ranges: tuple[str, ...], expected: tuple):
        assert compile_cidr(ranges) == expected


class TestValidation:
    @parameterized.expand(
        [
            ("empty", {"pattern": ""}, "Pattern cannot be empty"),
            ("missing", {"pattern": None}, "Pattern cannot be empty"),
            ("whitespace", {"pattern": "   "}, "Pattern cannot be empty"),
            ("a list on a pattern matcher", {"patterns": ["AcmeBot"]}, "Only IP range conditions"),
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
            # Ids are stored on team.modifiers, which is read on every query for the team.
            ("oversized rule id", {"id": "a" * 101}, "Rule id cannot be longer"),
        ]
    )
    def test_rejects_unusable_rules(self, _name: str, overrides: dict, expected_message: str):
        with pytest.raises(ValueError, match=expected_message):
            validate_rule(rule(**overrides))

    def test_rejects_a_rule_set_over_the_aggregate_condition_budget(self):
        # The per-list and per-rule caps multiply to 500 conditions; the aggregate budget is what
        # actually bounds a query's hyperscan work.
        rules = [
            rule(id=str(i), items=[condition(id=f"{i}-{j}") for j in range(MAX_CONDITIONS_PER_RULE)])
            for i in range(MAX_TOTAL_CONDITIONS // MAX_CONDITIONS_PER_RULE + 1)
        ]

        with pytest.raises(ValueError, match="across all rules"):
            validate_rule_set(rules)

    def test_rejects_a_rule_set_over_the_aggregate_ip_range_budget(self):
        per_rule = MAX_IP_RANGES_PER_CONDITION
        rules = [
            cidr_rule(id=str(i), patterns=separate_addresses(per_rule, start=i * per_rule))
            for i in range(MAX_TOTAL_IP_RANGES // per_rule + 1)
        ]

        with pytest.raises(ValueError, match="IP network blocks across all rules"):
            validate_rule_set(rules)

    def test_rejects_a_rule_with_too_many_conditions(self):
        # Every condition is a read added to every query that selects a classification field.
        overloaded = rule(items=[condition(id=str(i + 10)) for i in range(MAX_CONDITIONS_PER_RULE + 1)])

        with pytest.raises(ValueError, match="at most"):
            validate_rule(overloaded)

    @parameterized.expand(
        [
            # A shared id collapses entries in the id-keyed editor.
            ("two conditions share an id", [{"id": "a"}, {"id": "a"}]),
            ("a condition reuses the rule id", [{"id": "1"}]),
        ]
    )
    def test_rejects_colliding_condition_ids(self, _name: str, item_overrides: list[dict]):
        colliding = rule(items=[condition(**overrides) for overrides in item_overrides])

        with pytest.raises(ValueError, match="unique"):
            validate_rule(colliding)

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
            ("single address", {"patterns": ["192.0.2.7"]}),
            ("v4 range", {"patterns": ["192.0.2.0/24"]}),
            ("v6 range", {"patterns": ["2001:db8::/32"]}),
            ("host bits set", {"patterns": ["192.0.2.7/24"]}),
            ("a list across ip versions", {"patterns": ["192.0.2.0/24", "198.51.100.7", "2001:db8::/32"]}),
            ("a start-end range", {"patterns": ["192.0.2.10 - 192.0.2.40"]}),
            ("a range saved before conditions held a list", {"pattern": "192.0.2.0/24", "patterns": None}),
            ("as many ranges as a condition holds", {"patterns": separate_addresses(MAX_IP_RANGES_PER_CONDITION)}),
            (
                "overlapping ranges that merge under the block cap",
                {"patterns": [f"10.0.0.1-10.0.{n}.254" for n in range(1, 100)]},
            ),
        ]
    )
    def test_accepts_usable_ip_ranges(self, _name: str, overrides: dict):
        validate_rule(cidr_rule(**overrides))

    @parameterized.expand(
        [
            ("not an address", ["not-an-ip"], "'not-an-ip' is not a valid"),
            ("prefix too long", ["192.0.2.0/33"], "is not a valid"),
            ("empty", ["   "], "cannot be empty"),
            ("no ranges", [], "at least one"),
            # Python's ip_network keeps a zone identifier that ClickHouse toIPv6 later rejects, so a
            # saved rule would break every query reading a bot field. Reject it at validation.
            ("zone-scoped ipv6", ["fe80::1%eth0"], "zone identifier"),
            ("one bad entry in a list", ["192.0.2.0/24", "192.0.2.300", "2001:db8::/32"], "'192.0.2.300' is not"),
            ("a range across ip versions", ["192.0.2.1-2001:db8::1"], "same IP version"),
            ("a range that ends before it starts", ["192.0.2.40-192.0.2.10"], "must not come after its end"),
            ("too many entries", separate_addresses(MAX_IP_RANGES_PER_CONDITION + 1), "at most"),
            (
                "entries that cover too many network blocks",
                [f"10.0.{n}.1-10.0.{n}.6" for n in range(MAX_IP_RANGES_PER_CONDITION // 3)],
                "more than",
            ),
        ]
    )
    def test_rejects_unusable_ip_ranges(self, _name: str, patterns: list[str], expected_message: str):
        with pytest.raises(ValueError, match=expected_message):
            validate_rule(cidr_rule(patterns=patterns))

    def test_rejects_a_range_on_a_property_that_is_not_an_ip(self):
        # Comparing a user agent to a network range can never match, so it is a mistake worth
        # naming rather than a rule that silently does nothing.
        with pytest.raises(ValueError, match="IP ranges only work with"):
            validate_rule(rule(matcher=CustomBotMatcher.CIDR, pattern=None, patterns=["192.0.2.0/24"]))

    def test_rejects_a_property_outside_the_supported_set(self):
        raw = condition().model_dump()
        raw["key"] = "$some_other_property"

        with pytest.raises(ValueError, match="Cannot match on property"):
            validate_rule(rule(items=[CustomBotCondition.model_construct(**raw)]))


class TestParseRules:
    def test_keeps_parseable_rules_and_drops_what_does_not_parse(self):
        current = rule().model_dump(exclude_none=True)
        # A pre-combiner flat entry has no items, so it is dropped like any other unparseable entry.
        flat = {"id": "9", "name": "Flat", "key": "$raw_user_agent", "matcher": "contains", "pattern": "AcmeBot"}

        parsed = parse_rules([current, "garbage", flat, {"items": "not-a-list"}])

        assert [r.name for r in parsed] == ["Acme scraper"]

    def test_strict_raises_instead_of_dropping(self):
        # On the save paths a silently dropped rule reads as saved; the error has to surface.
        with pytest.raises(ValueError, match="Invalid bot rule"):
            parse_rules([{"pattern": "no items"}], strict=True)


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

    def test_rules_beyond_the_aggregate_condition_budget_are_dropped(self):
        # Client-supplied query modifiers never pass a save path, so the budget must hold at
        # compile time too or a crafted query forces one hyperscan call per condition per row.
        rules = [
            rule(id=str(i), name=f"Bot {i}", items=[condition(id=f"{i}-{j}") for j in range(MAX_CONDITIONS_PER_RULE)])
            for i in range(MAX_TOTAL_CONDITIONS // MAX_CONDITIONS_PER_RULE + 5)
        ]

        groups = compile_definitions(rules)

        total = sum(len(group.conditions) if isinstance(group, CompositeGroup) else 1 for group in groups)
        assert total <= MAX_TOTAL_CONDITIONS

    def test_rules_beyond_the_ip_range_budget_are_dropped(self):
        per_rule = MAX_IP_RANGES_PER_CONDITION
        rules = [
            rule(
                id=str(i),
                name=f"Bot {i}",
                items=[
                    condition(id=f"{i}-ua"),
                    condition(
                        id=f"{i}-ip",
                        key=CustomBotField.FIELD_IP,
                        matcher=CustomBotMatcher.CIDR,
                        pattern=None,
                        patterns=separate_addresses(per_rule, start=i * per_rule),
                    ),
                ],
            )
            for i in range(MAX_TOTAL_IP_RANGES // per_rule + 1)
        ]

        groups = compile_definitions(rules)

        assert (
            sum(
                ip_range_count(item.groups)
                for group in groups
                if isinstance(group, CompositeGroup)
                for item in group.conditions
                if isinstance(item, CidrCondition)
            )
            == MAX_TOTAL_IP_RANGES
        )

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

    def test_only_contiguous_rules_share_a_group(self):
        # List order is precedence: a later same-property rule must not jump the rule between them.
        groups = compile_definitions(
            [
                rule(id="1", name="First UA", pattern="First"),
                rule(id="2", name="By host", key=CustomBotField.FIELD_HOST, pattern="scraper.example.com"),
                rule(id="3", name="Last UA", pattern="Last"),
            ]
        )

        assert [[bot.name for bot in group.definitions] for group in groups if isinstance(group, PatternGroup)] == [
            ["First UA"],
            ["By host"],
            ["Last UA"],
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

    def test_a_bucket_does_not_reach_back_across_a_composite(self):
        # The editor promises list order is precedence. Sharing a bucket across the composite
        # would check the last rule ahead of the composite listed above it, so the label of an
        # event both match would go to the wrong rule.
        composite = rule(
            id="2",
            name="Headless 800x600",
            items=[
                condition(id="w", key=CustomBotField.FIELD_SCREEN_WIDTH, matcher=CustomBotMatcher.EXACT, pattern="800"),
                condition(
                    id="h", key=CustomBotField.FIELD_SCREEN_HEIGHT, matcher=CustomBotMatcher.EXACT, pattern="600"
                ),
            ],
        )
        groups = compile_definitions(
            [rule(id="1", name="First", pattern="First"), composite, rule(id="3", name="Last", pattern="Last")]
        )

        assert [type(group) for group in groups] == [PatternGroup, CompositeGroup, PatternGroup]
        assert isinstance(groups[0], PatternGroup)
        assert isinstance(groups[2], PatternGroup)
        assert [bot.name for bot in groups[0].definitions] == ["First"]
        assert [bot.name for bot in groups[2].definitions] == ["Last"]

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


class TestCompositeBranch:
    @parameterized.expand(
        [
            # A reachable OR condition matching means the full rule would match too, so the
            # reachable subset must still be evaluated instead of skipping the whole rule.
            ("OR keeps the reachable condition", FilterLogicalOperator.OR_, True),
            # A partial AND could flag events the full rule would not, so it must skip entirely.
            ("AND skips the whole rule", FilterLogicalOperator.AND_, False),
        ]
    )
    def test_a_composite_with_an_unreachable_property_follows_its_combiner(
        self, _name: str, combiner: FilterLogicalOperator, expected_branch: bool
    ):
        groups = compile_definitions(
            [
                rule(
                    combiner=combiner,
                    items=[
                        condition(id="ua", pattern="AcmeBot"),
                        condition(id="host", key=CustomBotField.FIELD_HOST, pattern="scraper.example.com"),
                    ],
                )
            ]
        )
        assert isinstance(groups[0], CompositeGroup)
        # A user agent not read from a properties object has no sibling to reach $host through.
        branch = _composite_branch(groups[0], [ast.Field(chain=["foo", "ua"])], "name")

        assert (branch is not None) == expected_branch


@pytest.mark.usefixtures("clickhouse_database")
class TestPatternsCompile(ClickhouseTestMixin, SimpleTestCase):
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
