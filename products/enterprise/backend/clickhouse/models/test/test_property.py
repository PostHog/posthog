from datetime import datetime
from typing import Literal, Union, cast
from uuid import UUID

import pytest
from freezegun.api import freeze_time
from posthog.test.base import (
    BaseTest,
    ClickhouseTestMixin,
    _create_event,
    _create_person,
    cleanup_materialized_columns,
    snapshot_clickhouse_queries,
)

from rest_framework.exceptions import ValidationError

from posthog.clickhouse.client import sync_execute
from posthog.constants import PropertyOperatorType
from posthog.models.cohort import Cohort
from posthog.models.element import Element
from posthog.models.filters import Filter
from posthog.models.instance_setting import get_instance_setting
from posthog.models.organization import Organization
from posthog.models.property import Property, TableWithProperties
from posthog.models.property.util import (
    PropertyGroup,
    get_property_string_expr,
    get_single_or_multi_property_string_expr,
    parse_prop_grouped_clauses,
    prop_filter_json_extract,
)
from posthog.models.team import Team
from posthog.queries.person_distinct_id_query import get_team_distinct_ids_query
from posthog.queries.person_query import PersonQuery
from posthog.queries.property_optimizer import PropertyOptimizer
from posthog.queries.util import PersonPropertiesMode

from products.enterprise.backend.clickhouse.materialized_columns.columns import materialize


class TestPropFormat(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _run_query(self, filter: Filter, **kwargs) -> list:
        query, params = parse_prop_grouped_clauses(
            property_group=filter.property_groups,
            allow_denormalized_props=True,
            team_id=self.team.pk,
            hogql_context=filter.hogql_context,
            **kwargs,
        )
        final_query = "SELECT uuid FROM events WHERE team_id = %(team_id)s {}".format(query)
        return sync_execute(
            final_query,
            {**params, **filter.hogql_context.values, "team_id": self.team.pk},
        )

    def test_prop_person(self):
        _create_person(
            distinct_ids=["some_other_id"],
            team_id=self.team.pk,
            properties={"email": "another@posthog.com"},
        )

        _create_person(
            distinct_ids=["some_id"],
            team_id=self.team.pk,
            properties={"email": "test@posthog.com"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_id",
            properties={"attr": "some_val"},
        )

        filter = Filter(data={"properties": [{"key": "email", "value": "test@posthog.com", "type": "person"}]})
        self.assertEqual(len(self._run_query(filter)), 1)

    def test_prop_event(self):
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"attr": "some_other_val"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"attr": "some_val"},
        )

        filter_exact = Filter(data={"properties": [{"key": "attr", "value": "some_val"}]})
        self.assertEqual(len(self._run_query(filter_exact)), 1)

        filter_regex = Filter(data={"properties": [{"key": "attr", "value": "some_.+_val", "operator": "regex"}]})
        self.assertEqual(len(self._run_query(filter_regex)), 1)

        filter_icontains = Filter(data={"properties": [{"key": "attr", "value": "Some_Val", "operator": "icontains"}]})
        self.assertEqual(len(self._run_query(filter_icontains)), 1)

        filter_not_icontains = Filter(
            data={"properties": [{"key": "attr", "value": "other", "operator": "not_icontains"}]}
        )
        self.assertEqual(len(self._run_query(filter_not_icontains)), 1)

    def test_prop_element(self):
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"attr": "some_other_val"},
            elements=[
                Element(
                    tag_name="a",
                    href="/a-url",
                    attr_class=["small"],
                    text="bla bla",
                    nth_child=1,
                    nth_of_type=0,
                ),
                Element(
                    tag_name="button",
                    attr_class=["btn", "btn-primary"],
                    nth_child=0,
                    nth_of_type=0,
                ),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="label", nth_child=0, nth_of_type=0, attr_id="nested"),
            ],
        )
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            properties={"attr": "some_val"},
            elements=[
                Element(
                    tag_name="a",
                    href="/a-url",
                    attr_class=["small"],
                    text='bla"bla',
                    attributes={},
                    nth_child=1,
                    nth_of_type=0,
                ),
                Element(
                    tag_name="button",
                    attr_class=["btn", "btn-secondary"],
                    nth_child=0,
                    nth_of_type=0,
                ),
                Element(tag_name="div", nth_child=0, nth_of_type=0),
                Element(tag_name="img", nth_child=0, nth_of_type=0, attr_id="nested"),
            ],
        )
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            elements=[
                Element(tag_name="a", href="/789", nth_child=0, nth_of_type=0),
                Element(
                    tag_name="button",
                    attr_class=["btn", "btn-tertiary"],
                    nth_child=0,
                    nth_of_type=0,
                ),
            ],
        )

        # selector

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "selector",
                        "value": [".btn"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 3)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "selector",
                        "value": ".btn",
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 3)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "selector",
                        "value": [".btn-primary"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "selector",
                        "value": [".btn-secondary"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "selector",
                        "value": [".btn-primary", ".btn-secondary"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 2)

        filter_selector_exact_empty = Filter(
            data={
                "properties": [
                    {
                        "key": "selector",
                        "value": [],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_selector_exact_empty)), 0)

        filter_selector_is_not_empty = Filter(
            data={
                "properties": [
                    {
                        "key": "selector",
                        "value": [],
                        "operator": "is_not",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_selector_is_not_empty)), 3)

        # tag_name

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "tag_name",
                        "value": ["div"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 2)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "tag_name",
                        "value": "div",
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 2)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "tag_name",
                        "value": ["img"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "tag_name",
                        "value": ["label"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "tag_name",
                        "value": ["img", "label"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 2)

        # href/text

        filter_href_exact = Filter(
            data={
                "properties": [
                    {
                        "key": "href",
                        "value": ["/a-url"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_href_exact)), 2)

        filter_href_exact_double = Filter(
            data={
                "properties": [
                    {
                        "key": "href",
                        "value": ["/a-url", "/789"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_href_exact_double)), 3)

        filter_href_exact_empty = Filter(
            data={"properties": [{"key": "href", "value": [], "operator": "exact", "type": "element"}]}
        )
        self.assertEqual(len(self._run_query(filter_href_exact_empty)), 0)

        filter_href_is_not = Filter(
            data={
                "properties": [
                    {
                        "key": "href",
                        "value": ["/a-url"],
                        "operator": "is_not",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_href_is_not)), 1)

        filter_href_is_not_double = Filter(
            data={
                "properties": [
                    {
                        "key": "href",
                        "value": ["/a-url", "/789"],
                        "operator": "is_not",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_href_is_not_double)), 0)

        filter_href_is_not_empty = Filter(
            data={
                "properties": [
                    {
                        "key": "href",
                        "value": [],
                        "operator": "is_not",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_href_is_not_empty)), 3)

        filter_href_exact_with_tag_name_is_not = Filter(
            data={
                "properties": [
                    {"key": "href", "value": ["/a-url"], "type": "element"},
                    {
                        "key": "tag_name",
                        "value": ["marquee"],
                        "operator": "is_not",
                        "type": "element",
                    },
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_href_exact_with_tag_name_is_not)), 2)

        filter_href_icontains = Filter(
            data={
                "properties": [
                    {
                        "key": "href",
                        "value": ["UrL"],
                        "operator": "icontains",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_href_icontains)), 2)

        filter_href_regex = Filter(
            data={
                "properties": [
                    {
                        "key": "href",
                        "value": "/a-.+",
                        "operator": "regex",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_href_regex)), 2)

        filter_href_not_regex = Filter(
            data={
                "properties": [
                    {
                        "key": "href",
                        "value": r"/\d+",
                        "operator": "not_regex",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_href_not_regex)), 2)

        filter_text_icontains_with_doublequote = Filter(
            data={
                "properties": [
                    {
                        "key": "text",
                        "value": 'bla"bla',
                        "operator": "icontains",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_text_icontains_with_doublequote)), 1)

        filter_text_is_set = Filter(
            data={
                "properties": [
                    {
                        "key": "text",
                        "value": "is_set",
                        "operator": "is_set",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_text_is_set)), 2)

        filter_text_is_not_set = Filter(
            data={
                "properties": [
                    {
                        "key": "text",
                        "value": "is_not_set",
                        "operator": "is_not_set",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter_text_is_not_set)), 1)

    def test_prop_element_with_space(self):
        _create_event(
            event="$autocapture",
            team=self.team,
            distinct_id="whatever",
            elements=[
                Element(tag_name="a", href="/789", nth_child=0, nth_of_type=0),
                Element(
                    tag_name="button",
                    attr_class=["btn space", "btn-tertiary"],
                    nth_child=0,
                    nth_of_type=0,
                ),
            ],
        )

        # selector

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "selector",
                        "value": ["button"],
                        "operator": "exact",
                        "type": "element",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 1)

    def test_prop_ints_saved_as_strings(self):
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": "0"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": "2"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": 2},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": "string"},
        )
        filter = Filter(data={"properties": [{"key": "test_prop", "value": "2"}]})
        self.assertEqual(len(self._run_query(filter)), 2)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 2}]})
        self.assertEqual(len(self._run_query(filter)), 2)

        # value passed as string
        filter = Filter(data={"properties": [{"key": "test_prop", "value": "1", "operator": "gt"}]})
        self.assertEqual(len(self._run_query(filter)), 2)
        filter = Filter(data={"properties": [{"key": "test_prop", "value": "3", "operator": "lt"}]})
        self.assertEqual(len(self._run_query(filter)), 3)

        # value passed as int
        filter = Filter(data={"properties": [{"key": "test_prop", "value": 1, "operator": "gt"}]})
        self.assertEqual(len(self._run_query(filter)), 2)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 3, "operator": "lt"}]})
        self.assertEqual(len(self._run_query(filter)), 3)

    def test_prop_decimals(self):
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": 1.4},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": 1.3},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": 2},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": 2.5},
        )

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 1.5}]})
        self.assertEqual(len(self._run_query(filter)), 0)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 1.2, "operator": "gt"}]})
        self.assertEqual(len(self._run_query(filter)), 4)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "1.2", "operator": "gt"}]})
        self.assertEqual(len(self._run_query(filter)), 4)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 2.3, "operator": "lt"}]})
        self.assertEqual(len(self._run_query(filter)), 3)

    @snapshot_clickhouse_queries
    def test_parse_groups(self):
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_id",
            properties={"attr_1": "val_1", "attr_2": "val_2"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_id",
            properties={"attr_1": "val_2"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_other_id",
            properties={"attr_1": "val_3"},
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "attr_1", "value": "val_1"},
                                {"key": "attr_2", "value": "val_2"},
                            ],
                        },
                        {"type": "OR", "values": [{"key": "attr_1", "value": "val_2"}]},
                    ],
                }
            }
        )

        self.assertEqual(len(self._run_query(filter)), 2)

    def test_parse_groups_invalid_type(self):
        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "AND",
                            "values": [
                                {"key": "attr", "value": "val_1"},
                                {"key": "attr_2", "value": "val_2"},
                            ],
                        },
                        {"type": "XOR", "values": [{"key": "attr", "value": "val_2"}]},
                    ],
                }
            }
        )
        with self.assertRaises(ValidationError):
            self._run_query(filter)

    @snapshot_clickhouse_queries
    def test_parse_groups_persons(self):
        _create_person(
            distinct_ids=["some_id"],
            team_id=self.team.pk,
            properties={"email": "1@posthog.com"},
        )

        _create_person(
            distinct_ids=["some_other_id"],
            team_id=self.team.pk,
            properties={"email": "2@posthog.com"},
        )
        _create_person(
            distinct_ids=["some_other_random_id"],
            team_id=self.team.pk,
            properties={"email": "X@posthog.com"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_id",
            properties={"attr": "val_1"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_other_id",
            properties={"attr": "val_3"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_other_random_id",
            properties={"attr": "val_3"},
        )

        filter = Filter(
            data={
                "properties": {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "1@posthog.com",
                                }
                            ],
                        },
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "email",
                                    "type": "person",
                                    "value": "2@posthog.com",
                                }
                            ],
                        },
                    ],
                }
            }
        )

        self.assertEqual(len(self._run_query(filter)), 2)


class TestPropDenormalized(ClickhouseTestMixin, BaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def _run_query(self, filter: Filter, join_person_tables=False) -> list:
        outer_properties = PropertyOptimizer().parse_property_groups(filter.property_groups).outer
        query, params = parse_prop_grouped_clauses(
            team_id=self.team.pk,
            property_group=outer_properties,
            allow_denormalized_props=True,
            person_properties_mode=PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            hogql_context=filter.hogql_context,
        )
        joins = ""
        if join_person_tables:
            person_query = PersonQuery(filter, self.team.pk)
            person_subquery, person_join_params = person_query.get_query()
            joins = f"""
                INNER JOIN ({get_team_distinct_ids_query(self.team.pk)}) AS pdi ON events.distinct_id = pdi.distinct_id
                INNER JOIN ({person_subquery}) person ON pdi.person_id = person.id
            """
            params.update(person_join_params)

        final_query = f"SELECT uuid FROM events {joins} WHERE team_id = %(team_id)s {query}"
        # Make sure we don't accidentally use json on the properties field
        self.assertNotIn("json", final_query.lower())
        return sync_execute(
            final_query,
            {**params, **filter.hogql_context.values, "team_id": self.team.pk},
        )

    def test_prop_event_denormalized(self):
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": "some_other_val"},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": "some_val"},
        )

        materialize("events", "test_prop")
        materialize("events", "something_else")

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val"}]})
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val", "operator": "is_not"}]})
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val", "operator": "is_set"}]})
        self.assertEqual(len(self._run_query(filter)), 2)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "some_val", "operator": "is_not_set"}]})
        self.assertEqual(len(self._run_query(filter)), 0)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": "_other_", "operator": "icontains"}]})
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "test_prop",
                        "value": "_other_",
                        "operator": "not_icontains",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter)), 1)

    def test_prop_person_denormalized(self):
        _create_person(
            distinct_ids=["some_id"],
            team_id=self.team.pk,
            properties={"email": "test@posthog.com"},
        )
        _create_event(event="$pageview", team=self.team, distinct_id="some_id")

        materialize("person", "email")

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "email",
                        "type": "person",
                        "value": "posthog",
                        "operator": "icontains",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter, join_person_tables=True)), 1)

        filter = Filter(
            data={
                "properties": [
                    {
                        "key": "email",
                        "type": "person",
                        "value": "posthog",
                        "operator": "not_icontains",
                    }
                ]
            }
        )
        self.assertEqual(len(self._run_query(filter, join_person_tables=True)), 0)

    def test_prop_person_groups_denormalized(self):
        _filter = {
            "properties": {
                "type": "OR",
                "values": [
                    {
                        "type": "OR",
                        "values": [
                            {
                                "key": "event_prop2",
                                "value": ["foo2", "bar2"],
                                "type": "event",
                                "operator": None,
                            },
                            {
                                "key": "person_prop2",
                                "value": "efg2",
                                "type": "person",
                                "operator": None,
                            },
                        ],
                    },
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "event_prop",
                                "value": ["foo", "bar"],
                                "type": "event",
                                "operator": None,
                            },
                            {
                                "key": "person_prop",
                                "value": "efg",
                                "type": "person",
                                "operator": None,
                            },
                        ],
                    },
                ],
            }
        }

        filter = Filter(data=_filter)

        _create_person(distinct_ids=["some_id_1"], team_id=self.team.pk, properties={})
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_id_1",
            properties={"event_prop2": "foo2"},
        )

        _create_person(
            distinct_ids=["some_id_2"],
            team_id=self.team.pk,
            properties={"person_prop2": "efg2"},
        )
        _create_event(event="$pageview", team=self.team, distinct_id="some_id_2")

        _create_person(
            distinct_ids=["some_id_3"],
            team_id=self.team.pk,
            properties={"person_prop": "efg"},
        )
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="some_id_3",
            properties={"event_prop": "foo"},
        )

        materialize("events", "event_prop")
        materialize("events", "event_prop2")
        materialize("person", "person_prop")
        materialize("person", "person_prop2")
        self.assertEqual(len(self._run_query(filter, join_person_tables=True)), 3)

    def test_prop_event_denormalized_ints(self):
        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": 0},
        )

        _create_event(
            event="$pageview",
            team=self.team,
            distinct_id="whatever",
            properties={"test_prop": 2},
        )

        materialize("events", "test_prop")
        materialize("events", "something_else")

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 1, "operator": "gt"}]})
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 1, "operator": "lt"}]})
        self.assertEqual(len(self._run_query(filter)), 1)

        filter = Filter(data={"properties": [{"key": "test_prop", "value": 0}]})
        self.assertEqual(len(self._run_query(filter)), 1)

    def test_get_property_string_expr(self):
        string_expr = get_property_string_expr("events", "some_non_mat_prop", "'some_non_mat_prop'", "properties")
        self.assertEqual(
            string_expr,
            (
                "replaceRegexpAll(JSONExtractRaw(properties, 'some_non_mat_prop'), '^\"|\"$', '')",
                False,
            ),
        )

        string_expr = get_property_string_expr(
            "events",
            "some_non_mat_prop",
            "'some_non_mat_prop'",
            "properties",
            table_alias="e",
        )
        self.assertEqual(
            string_expr,
            (
                "replaceRegexpAll(JSONExtractRaw(e.properties, 'some_non_mat_prop'), '^\"|\"$', '')",
                False,
            ),
        )

        materialize("events", "some_mat_prop")
        string_expr = get_property_string_expr("events", "some_mat_prop", "'some_mat_prop'", "properties")
        self.assertEqual(string_expr, ('"mat_some_mat_prop"', True))

        string_expr = get_property_string_expr(
            "events", "some_mat_prop", "'some_mat_prop'", "properties", table_alias="e"
        )
        self.assertEqual(string_expr, ('e."mat_some_mat_prop"', True))

        materialize("events", "some_mat_prop2", table_column="person_properties")
        materialize("events", "some_mat_prop3", table_column="group2_properties")
        string_expr = get_property_string_expr(
            "events",
            "some_mat_prop2",
            "x",
            "properties",
            materialised_table_column="person_properties",
        )
        self.assertEqual(string_expr, ('"mat_pp_some_mat_prop2"', True))


@pytest.mark.django_db
def test_parse_prop_clauses_defaults(snapshot):
    filter = Filter(
        data={
            "properties": [
                {"key": "event_prop", "value": "value"},
                {
                    "key": "email",
                    "type": "person",
                    "value": "posthog",
                    "operator": "icontains",
                },
            ]
        }
    )

    assert (
        parse_prop_grouped_clauses(
            property_group=filter.property_groups,
            allow_denormalized_props=False,
            team_id=1,
            hogql_context=filter.hogql_context,
        )
        == snapshot
    )
    assert (
        parse_prop_grouped_clauses(
            property_group=filter.property_groups,
            person_properties_mode=PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            allow_denormalized_props=False,
            team_id=1,
            hogql_context=filter.hogql_context,
        )
        == snapshot
    )
    assert (
        parse_prop_grouped_clauses(
            team_id=1,
            property_group=filter.property_groups,
            person_properties_mode=PersonPropertiesMode.DIRECT,
            allow_denormalized_props=False,
            hogql_context=filter.hogql_context,
        )
        == snapshot
    )


@pytest.mark.django_db
def test_parse_prop_clauses_precalculated_cohort(snapshot):
    Cohort.objects.filter(pk=42).delete()
    org = Organization.objects.create(name="other org")

    team = Team.objects.create(organization=org)
    # force pk for snapshot consistency
    cohort = Cohort.objects.create(pk=42, team=team, groups=[{"event_id": "$pageview", "days": 7}], name="cohort")

    filter = Filter(
        data={"properties": [{"key": "id", "value": cohort.pk, "type": "precalculated-cohort"}]},
        team=team,
    )

    assert (
        parse_prop_grouped_clauses(
            team_id=1,
            property_group=filter.property_groups,
            person_properties_mode=PersonPropertiesMode.USING_SUBQUERY,
            allow_denormalized_props=False,
            person_id_joined_alias="pdi.person_id",
            hogql_context=filter.hogql_context,
        )
        == snapshot
    )


# Regression test for: https://github.com/PostHog/posthog/pull/9283
@pytest.mark.django_db
def test_parse_prop_clauses_funnel_step_element_prepend_regression(snapshot):
    filter = Filter(
        data={
            "properties": [
                {
                    "key": "text",
                    "type": "element",
                    "value": "Insights1",
                    "operator": "exact",
                }
            ]
        }
    )

    assert (
        parse_prop_grouped_clauses(
            property_group=filter.property_groups,
            allow_denormalized_props=False,
            team_id=1,
            prepend="PREPEND",
            hogql_context=filter.hogql_context,
        )
        == snapshot
    )


@pytest.mark.django_db
def test_parse_groups_persons_edge_case_with_single_filter(snapshot):
    filter = Filter(
        data={
            "properties": {
                "type": "OR",
                "values": [{"key": "email", "type": "person", "value": "1@posthog.com"}],
            }
        }
    )
    assert (
        parse_prop_grouped_clauses(
            team_id=1,
            property_group=filter.property_groups,
            person_properties_mode=PersonPropertiesMode.USING_PERSON_PROPERTIES_COLUMN,
            allow_denormalized_props=True,
            hogql_context=filter.hogql_context,
        )
        == snapshot
    )


TEST_BREAKDOWN_PROCESSING = [
    (
        "$browser",
        "events",
        "prop",
        "properties",
        (
            "replaceRegexpAll(JSONExtractRaw(properties, %(breakdown_param_1)s), '^\"|\"$', '') AS prop",
            {"breakdown_param_1": "$browser"},
        ),
    ),
    (
        ["$browser"],
        "events",
        "value",
        "properties",
        (
            "array(replaceRegexpAll(JSONExtractRaw(properties, %(breakdown_param_1)s), '^\"|\"$', '')) AS value",
            {"breakdown_param_1": "$browser"},
        ),
    ),
    (
        ["$browser", "$browser_version"],
        "events",
        "prop",
        "properties",
        (
            "array(replaceRegexpAll(JSONExtractRaw(properties, %(breakdown_param_1)s), '^\"|\"$', ''),replaceRegexpAll(JSONExtractRaw(properties, %(breakdown_param_2)s), '^\"|\"$', '')) AS prop",
            {"breakdown_param_1": "$browser", "breakdown_param_2": "$browser_version"},
        ),
    ),
]


@pytest.mark.django_db
@pytest.mark.parametrize("breakdown, table, query_alias, column, expected", TEST_BREAKDOWN_PROCESSING)
def test_breakdown_query_expression(
    clean_up_materialised_columns,
    breakdown: Union[str, list[str]],
    table: TableWithProperties,
    query_alias: Literal["prop", "value"],
    column: str,
    expected: str,
):
    actual = get_single_or_multi_property_string_expr(breakdown, table, query_alias, column)

    assert actual == expected


TEST_BREAKDOWN_PROCESSING_MATERIALIZED = [
    (
        ["$browser"],
        "events",
        "value",
        "properties",
        "person_properties",
        (
            "array(replaceRegexpAll(JSONExtractRaw(properties, %(breakdown_param_1)s), '^\"|\"$', '')) AS value",
            {"breakdown_param_1": "$browser"},
        ),
        ('array("mat_pp_$browser") AS value', {"breakdown_param_1": "$browser"}),
    )
]


@pytest.mark.django_db
@pytest.mark.parametrize(
    "breakdown, table, query_alias, column, materialise_column, expected_with, expected_without",
    TEST_BREAKDOWN_PROCESSING_MATERIALIZED,
)
def test_breakdown_query_expression_materialised(
    clean_up_materialised_columns,
    breakdown: Union[str, list[str]],
    table: TableWithProperties,
    query_alias: Literal["prop", "value"],
    column: str,
    materialise_column: str,
    expected_with: str,
    expected_without: str,
):
    from posthog.models.team import util

    util.can_enable_actor_on_events = True

    materialize(table, breakdown[0], table_column="properties")
    actual = get_single_or_multi_property_string_expr(
        breakdown,
        table,
        query_alias,
        column,
        materialised_table_column=materialise_column,
    )
    assert actual == expected_with

    materialize(table, breakdown[0], table_column=materialise_column)  # type: ignore
    actual = get_single_or_multi_property_string_expr(
        breakdown,
        table,
        query_alias,
        column,
        materialised_table_column=materialise_column,
    )

    assert actual == expected_without


@pytest.fixture
def test_events(db, team) -> list[UUID]:
    return [
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"email": "test@posthog.com"},
            group2_properties={"email": "test@posthog.com"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"email": "mongo@example.com"},
            group2_properties={"email": "mongo@example.com"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"attr": "some_val"},
            group2_properties={"attr": "some_val"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"attr": "50"},
            group2_properties={"attr": "50"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"attr": 5},
            group2_properties={"attr": 5},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            # unix timestamp in seconds
            properties={"unix_timestamp": int(datetime(2021, 4, 1, 18).timestamp())},
            group2_properties={"unix_timestamp": int(datetime(2021, 4, 1, 18).timestamp())},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            # unix timestamp in seconds
            properties={"unix_timestamp": int(datetime(2021, 4, 1, 19).timestamp())},
            group2_properties={"unix_timestamp": int(datetime(2021, 4, 1, 19).timestamp())},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"long_date": f"{datetime(2021, 4, 1, 18):%Y-%m-%d %H:%M:%S%z}"},
            group2_properties={"long_date": f"{datetime(2021, 4, 1, 18):%Y-%m-%d %H:%M:%S%z}"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"long_date": f"{datetime(2021, 4, 1, 19):%Y-%m-%d %H:%M:%S%z}"},
            group2_properties={"long_date": f"{datetime(2021, 4, 1, 19):%Y-%m-%d %H:%M:%S%z}"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"short_date": f"{datetime(2021, 4, 4):%Y-%m-%d}"},
            group2_properties={"short_date": f"{datetime(2021, 4, 4):%Y-%m-%d}"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"short_date": f"{datetime(2021, 4, 6):%Y-%m-%d}"},
            group2_properties={"short_date": f"{datetime(2021, 4, 6):%Y-%m-%d}"},
        ),
        # unix timestamp in seconds with fractions of a second
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"sdk_$time": 1639427152.339},
            group2_properties={"sdk_$time": 1639427152.339},
        ),
        # unix timestamp in milliseconds
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"unix_timestamp_milliseconds": 1641977394339},
            group2_properties={"unix_timestamp_milliseconds": 1641977394339},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"rfc_822_time": "Wed, 02 Oct 2002 15:00:00 +0200"},
            group2_properties={"rfc_822_time": "Wed, 02 Oct 2002 15:00:00 +0200"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"iso_8601_$time": f"{datetime(2021, 4, 1, 19):%Y-%m-%dT%H:%M:%S%Z}"},
            group2_properties={"iso_8601_$time": f"{datetime(2021, 4, 1, 19):%Y-%m-%dT%H:%M:%S%Z}"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"full_date_increasing_$time": f"{datetime(2021, 4, 1, 19):%d-%m-%Y %H:%M:%S}"},
            group2_properties={"full_date_increasing_$time": f"{datetime(2021, 4, 1, 19):%d-%m-%Y %H:%M:%S}"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"with_slashes_$time": f"{datetime(2021, 4, 1, 19):%Y/%m/%d %H:%M:%S}"},
            group2_properties={"with_slashes_$time": f"{datetime(2021, 4, 1, 19):%Y/%m/%d %H:%M:%S}"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"with_slashes_increasing_$time": f"{datetime(2021, 4, 1, 19):%d/%m/%Y %H:%M:%S}"},
            group2_properties={"with_slashes_increasing_$time": f"{datetime(2021, 4, 1, 19):%d/%m/%Y %H:%M:%S}"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            # seven digit unix timestamp in seconds - 7840800
            # Clickhouse cannot parse this. It isn't matched in tests from TEST_PROPERTIES
            properties={"unix_timestamp": int(datetime(1970, 4, 1, 18).timestamp())},
            group2_properties={"unix_timestamp": int(datetime(1970, 4, 1, 18).timestamp())},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            # nine digit unix timestamp in seconds - 323460000
            properties={"unix_timestamp": int(datetime(1980, 4, 1, 18).timestamp())},
            group2_properties={"unix_timestamp": int(datetime(1980, 4, 1, 18).timestamp())},
        ),
        _create_event(
            # matched by exact date test
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"date_only": f"{datetime(2021, 4, 1):%d/%m/%Y}"},
            group2_properties={"date_only": f"{datetime(2021, 4, 1):%d/%m/%Y}"},
        ),
        _create_event(
            # should not be matched by exact date test
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"date_only": f"{datetime(2021, 4, 1, 11):%d/%m/%Y}"},
            group2_properties={"date_only": f"{datetime(2021, 4, 1, 11):%d/%m/%Y}"},
        ),
        _create_event(
            # not matched by exact date test
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"date_only": f"{datetime(2021, 4, 2):%d/%m/%Y}"},
            group2_properties={"date_only": f"{datetime(2021, 4, 2):%d/%m/%Y}"},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"date_only_matched_against_date_and_time": f"{datetime(2021, 3, 31, 18):%d/%m/%Y %H:%M:%S}"},
            group2_properties={
                "date_only_matched_against_date_and_time": f"{datetime(2021, 3, 31, 18):%d/%m/%Y %H:%M:%S}"
            },
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            properties={"date_only_matched_against_date_and_time": int(datetime(2021, 3, 31, 14).timestamp())},
            group2_properties={"date_only_matched_against_date_and_time": int(datetime(2021, 3, 31, 14).timestamp())},
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            # include milliseconds, to prove they're ignored in the query
            properties={
                "date_exact_including_seconds_and_milliseconds": f"{datetime(2021, 3, 31, 18, 12, 12, 12):%d/%m/%Y %H:%M:%S.%f}"
            },
            group2_properties={
                "date_exact_including_seconds_and_milliseconds": f"{datetime(2021, 3, 31, 18, 12, 12, 12):%d/%m/%Y %H:%M:%S.%f}"
            },
        ),
        _create_event(
            event="$pageview",
            team=team,
            distinct_id="whatever",
            # include milliseconds, to prove they're don't cause a date to be included in an after filter
            properties={
                "date_exact_including_seconds_and_milliseconds": f"{datetime(2021, 3, 31, 23, 59, 59, 12):%d/%m/%Y %H:%M:%S.%f}"
            },
            group2_properties={
                "date_exact_including_seconds_and_milliseconds": f"{datetime(2021, 3, 31, 23, 59, 59, 12):%d/%m/%Y %H:%M:%S.%f}"
            },
        ),
    ]


@pytest.fixture
def clean_up_materialised_columns():
    try:
        yield
    finally:
        # after test cleanup
        cleanup_materialized_columns()


TEST_PROPERTIES = [
    pytest.param(Property(key="email", value="test@posthog.com"), [0]),
    pytest.param(Property(key="email", value="test@posthog.com", operator="exact"), [0]),
    pytest.param(
        Property(
            key="email",
            value=["pineapple@pizza.com", "mongo@example.com"],
            operator="exact",
        ),
        [1],
    ),
    pytest.param(
        Property(key="attr", value="5"),
        [4],
        id="matching a number only matches event index 4 from test_events",
    ),
    pytest.param(
        Property(key="email", value="test@posthog.com", operator="is_not"),
        range(1, 27),
        id="matching on email is not a value matches all but the first event from test_events",
    ),
    pytest.param(
        Property(
            key="email",
            value=["test@posthog.com", "mongo@example.com"],
            operator="is_not",
        ),
        range(2, 27),
        id="matching on email is not a value matches all but the first two events from test_events",
    ),
    pytest.param(Property(key="email", value=r".*est@.*", operator="regex"), [0]),
    pytest.param(Property(key="email", value=r"?.", operator="regex"), []),
    pytest.param(Property(key="email", operator="is_set", value="is_set"), [0, 1]),
    pytest.param(
        Property(key="email", operator="is_not_set", value="is_not_set"),
        range(2, 27),
        id="matching for email property not being set matches all but the first two events from test_events",
    ),
    pytest.param(
        Property(key="unix_timestamp", operator="is_date_before", value="2021-04-02"),
        [5, 6, 19],
        id="matching before a unix timestamp only querying by date",
    ),
    pytest.param(
        Property(key="unix_timestamp", operator="is_date_after", value="2021-03-31"),
        [5, 6],
        id="matching after a unix timestamp only querying by date",
    ),
    pytest.param(
        Property(key="unix_timestamp", operator="is_date_before", value="2021-04-01 18:30:00"),
        [5, 19],
        id="matching before a unix timestamp querying by date and time",
    ),
    pytest.param(
        Property(key="unix_timestamp", operator="is_date_after", value="2021-04-01 18:30:00"),
        [6],
        id="matching after a unix timestamp querying by date and time",
    ),
    pytest.param(Property(key="long_date", operator="is_date_before", value="2021-04-02"), [7, 8]),
    pytest.param(
        Property(key="long_date", operator="is_date_after", value="2021-03-31"),
        [7, 8],
        id="match after date only value against date and time formatted property",
    ),
    pytest.param(
        Property(key="long_date", operator="is_date_before", value="2021-04-01 18:30:00"),
        [7],
    ),
    pytest.param(
        Property(key="long_date", operator="is_date_after", value="2021-04-01 18:30:00"),
        [8],
    ),
    pytest.param(Property(key="short_date", operator="is_date_before", value="2021-04-05"), [9]),
    pytest.param(Property(key="short_date", operator="is_date_after", value="2021-04-05"), [10]),
    pytest.param(
        Property(key="short_date", operator="is_date_before", value="2021-04-07"),
        [9, 10],
    ),
    pytest.param(
        Property(key="short_date", operator="is_date_after", value="2021-04-03"),
        [9, 10],
    ),
    pytest.param(
        Property(key="sdk_$time", operator="is_date_before", value="2021-12-25"),
        [11],
        id="matching a unix timestamp in seconds with fractional seconds after the decimal point",
    ),
    pytest.param(
        Property(
            key="unix_timestamp_milliseconds",
            operator="is_date_after",
            value="2022-01-11",
        ),
        [12],
        id="matching unix timestamp in milliseconds after a given date (which ClickHouse doesn't support)",
    ),
    pytest.param(
        Property(
            key="unix_timestamp_milliseconds",
            operator="is_date_before",
            value="2022-01-13",
        ),
        [12],
        id="matching unix timestamp in milliseconds before a given date (which ClickHouse doesn't support)",
    ),
    pytest.param(
        Property(key="rfc_822_time", operator="is_date_before", value="2002-10-02 17:01:00"),
        [13],
        id="matching rfc 822 format date with timeszone offset before a given date",
    ),
    pytest.param(
        Property(key="rfc_822_time", operator="is_date_after", value="2002-10-02 14:59:00"),
        [],
        id="matching rfc 822 format date takes into account timeszone offset after a given date",
    ),
    pytest.param(
        Property(key="rfc_822_time", operator="is_date_after", value="2002-10-02 12:59:00"),
        [13],
        id="matching rfc 822 format date after a given date",
    ),
    pytest.param(
        Property(key="iso_8601_$time", operator="is_date_before", value="2021-04-01 20:00:00"),
        [14],
        id="matching ISO 8601 format date before a given date",
    ),
    pytest.param(
        Property(key="iso_8601_$time", operator="is_date_after", value="2021-04-01 18:00:00"),
        [14],
        id="matching ISO 8601 format date after a given date",
    ),
    pytest.param(
        Property(
            key="full_date_increasing_$time",
            operator="is_date_before",
            value="2021-04-01 20:00:00",
        ),
        [15],
        id="matching full format date with date parts n increasing order before a given date",
    ),
    pytest.param(
        Property(
            key="full_date_increasing_$time",
            operator="is_date_after",
            value="2021-04-01 18:00:00",
        ),
        [15],
        id="matching full format date with date parts in increasing order after a given date",
    ),
    pytest.param(
        Property(
            key="with_slashes_$time",
            operator="is_date_before",
            value="2021-04-01 20:00:00",
        ),
        [16],
        id="matching full format date with date parts separated by slashes before a given date",
    ),
    pytest.param(
        Property(
            key="with_slashes_$time",
            operator="is_date_after",
            value="2021-04-01 18:00:00",
        ),
        [16],
        id="matching full format date with date parts separated by slashes after a given date",
    ),
    pytest.param(
        Property(
            key="with_slashes_increasing_$time",
            operator="is_date_before",
            value="2021-04-01 20:00:00",
        ),
        [17],
        id="matching full format date with date parts increasing in size and separated by slashes before a given date",
    ),
    pytest.param(
        Property(
            key="with_slashes_increasing_$time",
            operator="is_date_after",
            value="2021-04-01 18:00:00",
        ),
        [17],
        id="matching full format date with date parts increasing in size and separated by slashes after a given date",
    ),
    pytest.param(
        Property(key="date_only", operator="is_date_exact", value="2021-04-01"),
        [20, 21],
        id="can match dates exactly",
    ),
    pytest.param(
        Property(
            key="date_only_matched_against_date_and_time",
            operator="is_date_exact",
            value="2021-03-31",
        ),
        [23, 24],
        id="can match dates exactly against datetimes and unix timestamps",
    ),
    pytest.param(
        Property(
            key="date_exact_including_seconds_and_milliseconds",
            operator="is_date_exact",
            value="2021-03-31 18:12:12",
        ),
        [25],
        id="can match date times exactly against datetimes with milliseconds",
    ),
    pytest.param(
        Property(
            key="date_exact_including_seconds_and_milliseconds",
            operator="is_date_after",
            value="2021-03-31",
        ),
        [],
        id="can match date only filter after against datetime with milliseconds",
    ),
    pytest.param(
        Property(key="date_only", operator="is_date_after", value="2021-04-01"),
        [22],
        id="can match after date only values",
    ),
    pytest.param(
        Property(key="date_only", operator="is_date_before", value="2021-04-02"),
        [20, 21],
        id="can match before date only values",
    ),
]


@pytest.mark.parametrize("property,expected_event_indexes", TEST_PROPERTIES)
@freeze_time("2021-04-01T01:00:00.000Z")
def test_prop_filter_json_extract(test_events, clean_up_materialised_columns, property, expected_event_indexes, team):
    query, params = prop_filter_json_extract(property, 0, allow_denormalized_props=False)
    uuids = sorted(
        [
            str(uuid)
            for (uuid,) in sync_execute(
                f"SELECT uuid FROM events WHERE team_id = %(team_id)s {query}",
                {"team_id": team.pk, **params},
            )
        ]
    )
    expected = sorted([test_events[index] for index in expected_event_indexes])

    assert len(uuids) == len(expected)  # helpful when diagnosing assertion failure below
    assert uuids == expected


@pytest.mark.parametrize("property,expected_event_indexes", TEST_PROPERTIES)
@freeze_time("2021-04-01T01:00:00.000Z")
def test_prop_filter_json_extract_materialized(
    test_events, clean_up_materialised_columns, property, expected_event_indexes, team
):
    materialize("events", property.key)

    query, params = prop_filter_json_extract(property, 0, allow_denormalized_props=True)

    assert "JSONExtract" not in query

    uuids = sorted(
        [
            str(uuid)
            for (uuid,) in sync_execute(
                f"SELECT uuid FROM events WHERE team_id = %(team_id)s {query}",
                {"team_id": team.pk, **params},
            )
        ]
    )
    expected = sorted([test_events[index] for index in expected_event_indexes])

    assert uuids == expected


@pytest.mark.parametrize("property,expected_event_indexes", TEST_PROPERTIES)
@freeze_time("2021-04-01T01:00:00.000Z")
def test_prop_filter_json_extract_person_on_events_materialized(
    test_events, clean_up_materialised_columns, property, expected_event_indexes, team
):
    if not get_instance_setting("PERSON_ON_EVENTS_ENABLED"):
        return

    # simulates a group property being materialised
    materialize("events", property.key, table_column="group2_properties")

    query, params = prop_filter_json_extract(property, 0, allow_denormalized_props=True)
    # this query uses the `properties` column, thus the materialized column is different.
    assert ("JSON" in query) or ("AND 1 = 2" == query)

    query, params = prop_filter_json_extract(
        property, 0, allow_denormalized_props=True, use_event_column="group2_properties"
    )
    assert "JSON" not in query

    uuids = sorted(
        [
            str(uuid)
            for (uuid,) in sync_execute(
                f"SELECT uuid FROM events WHERE team_id = %(team_id)s {query}",
                {"team_id": team.pk, **params},
            )
        ]
    )
    expected = sorted([test_events[index] for index in expected_event_indexes])

    assert uuids == expected


def test_combine_group_properties():
    propertyA = Property(key="a", operator="exact", value=["a", "b", "c"])
    propertyB = Property(key="b", operator="exact", value=["d", "e", "f"])
    propertyC = Property(key="c", operator="exact", value=["g", "h", "i"])
    propertyD = Property(key="d", operator="exact", value=["j", "k", "l"])

    property_group = PropertyGroup(PropertyOperatorType.OR, [propertyA, propertyB])

    combined_group = property_group.combine_properties(PropertyOperatorType.AND, [propertyC, propertyD])
    assert combined_group.to_dict() == {
        "type": "AND",
        "values": [
            {
                "type": "OR",
                "values": [
                    {
                        "key": "a",
                        "operator": "exact",
                        "value": ["a", "b", "c"],
                        "type": "event",
                    },
                    {
                        "key": "b",
                        "operator": "exact",
                        "value": ["d", "e", "f"],
                        "type": "event",
                    },
                ],
            },
            {
                "type": "AND",
                "values": [
                    {
                        "key": "c",
                        "operator": "exact",
                        "value": ["g", "h", "i"],
                        "type": "event",
                    },
                    {
                        "key": "d",
                        "operator": "exact",
                        "value": ["j", "k", "l"],
                        "type": "event",
                    },
                ],
            },
        ],
    }

    combined_group = property_group.combine_properties(PropertyOperatorType.OR, [propertyC, propertyD])
    assert combined_group.to_dict() == {
        "type": "OR",
        "values": [
            {
                "type": "OR",
                "values": [
                    {
                        "key": "a",
                        "operator": "exact",
                        "value": ["a", "b", "c"],
                        "type": "event",
                    },
                    {
                        "key": "b",
                        "operator": "exact",
                        "value": ["d", "e", "f"],
                        "type": "event",
                    },
                ],
            },
            {
                "type": "AND",
                "values": [
                    {
                        "key": "c",
                        "operator": "exact",
                        "value": ["g", "h", "i"],
                        "type": "event",
                    },
                    {
                        "key": "d",
                        "operator": "exact",
                        "value": ["j", "k", "l"],
                        "type": "event",
                    },
                ],
            },
        ],
    }

    combined_group = property_group.combine_properties(PropertyOperatorType.OR, [])
    assert combined_group.to_dict() == {
        "type": "OR",
        "values": [
            {
                "key": "a",
                "operator": "exact",
                "value": ["a", "b", "c"],
                "type": "event",
            },
            {
                "key": "b",
                "operator": "exact",
                "value": ["d", "e", "f"],
                "type": "event",
            },
        ],
    }

    combined_group = PropertyGroup(PropertyOperatorType.AND, cast(list[Property], [])).combine_properties(
        PropertyOperatorType.OR, [propertyC, propertyD]
    )
    assert combined_group.to_dict() == {
        "type": "AND",
        "values": [
            {
                "key": "c",
                "operator": "exact",
                "value": ["g", "h", "i"],
                "type": "event",
            },
            {
                "key": "d",
                "operator": "exact",
                "value": ["j", "k", "l"],
                "type": "event",
            },
        ],
    }


def test_session_property_validation():
    # Property key not valid for type session
    with pytest.raises(ValidationError):
        filter = Filter(
            data={
                "properties": [
                    {
                        "type": "session",
                        "key": "some_prop",
                        "value": 0,
                        "operator": "gt",
                    }
                ]
            }
        )
        parse_prop_grouped_clauses(
            team_id=1,
            property_group=filter.property_groups,
            hogql_context=filter.hogql_context,
        )

    # Operator not valid for $session_duration
    with pytest.raises(ValidationError):
        filter = Filter(
            data={
                "properties": [
                    {
                        "type": "session",
                        "key": "$session_duration",
                        "value": 0,
                        "operator": "is_set",
                    }
                ]
            }
        )
        parse_prop_grouped_clauses(
            team_id=1,
            property_group=filter.property_groups,
            hogql_context=filter.hogql_context,
        )

    # Value not valid for $session_duration
    with pytest.raises(ValidationError):
        filter = Filter(
            data={
                "properties": [
                    {
                        "type": "session",
                        "key": "$session_duration",
                        "value": "hey",
                        "operator": "gt",
                    }
                ]
            }
        )
        parse_prop_grouped_clauses(
            team_id=1,
            property_group=filter.property_groups,
            hogql_context=filter.hogql_context,
        )

    # Valid property values
    filter = Filter(
        data={
            "properties": [
                {
                    "type": "session",
                    "key": "$session_duration",
                    "value": "100",
                    "operator": "gt",
                }
            ]
        }
    )
    parse_prop_grouped_clauses(
        team_id=1,
        property_group=filter.property_groups,
        hogql_context=filter.hogql_context,
    )
