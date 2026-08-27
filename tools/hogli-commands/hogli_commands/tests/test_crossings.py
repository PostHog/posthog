"""Tests for the model-crossing use classifier."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from hogli_commands.product import crossings
from hogli_commands.product.crossings import CrossingClass, classify_use, kind_is_allowed
from parameterized import parameterized

ALERT = CrossingClass("alerts", "AlertConfiguration", "products.alerts.backend.models.alert")
LOOKUP = {ALERT.label.lower(): ALERT.label}


def _candidate(source: str, dotted: str = "posthog.api.consumer") -> crossings._Candidate:
    encoded = textwrap.dedent(source).encode()
    package = dotted.rsplit(".", 1)[0]
    imports = crossings._read_imports(encoded, package)
    return crossings._Candidate(Path(f"{dotted.replace('.', '/')}.py"), dotted, imports, b"get_model" in encoded)


def classify(source: str) -> list[str]:
    candidate = _candidate(source)
    origins = crossings._origins([candidate], [ALERT])
    names = crossings._bound_names(candidate, origins)
    modules = {export.module for export in origins}
    aliases = {a.alias: a.module for a in candidate.imports.module_aliases if a.module in modules}
    tree = ast.parse(textwrap.dedent(source))
    parents = crossings._parent_map(tree)
    return [classify_use(node, parents) for node, _ in crossings._class_nodes(tree, names, aliases, origins)]


IMPORT = "from products.alerts.backend.models.alert import AlertConfiguration\n"


class TestClassifyUse:
    @pytest.mark.parametrize(
        "body,expected",
        [
            # Allowed: nothing here can hand the consumer a model instance.
            ("def f(a: AlertConfiguration) -> AlertConfiguration: ...", ["annotation", "annotation"]),
            ("def f() -> list[AlertConfiguration | None]: ...", ["annotation"]),
            ("x: dict[str, AlertConfiguration] = {}", ["annotation"]),
            ("try:\n    pass\nexcept AlertConfiguration.DoesNotExist:\n    pass", ["exception"]),
            ("s = AlertConfiguration.Status.FIRING", ["nested-class-attr(Status)"]),
            ("n = AlertConfiguration._meta.db_table", ["_meta"]),
            ("f = AlertConfiguration._meta.get_field('insight')", ["_meta"]),
            (
                "ids = AlertConfiguration.objects.filter(team=t).values_list('id', flat=True)",
                ["scalar-chain(values_list)"],
            ),
            ("n = AlertConfiguration.objects.count()", ["scalar-chain(count)"]),
            ("q = Exists(AlertConfiguration.objects.filter(insight=OuterRef('pk')))", ["subquery(Exists)"]),
            # Disallowed: each of these puts a model instance, a write, or a lock in the consumer.
            ("a = AlertConfiguration.objects.get(pk=1)", ["instance-single"]),
            ("a = AlertConfiguration._meta.default_manager.get(pk=1)", ["instance-single"]),
            ("a = AlertConfiguration._meta.model.objects.get(pk=1)", ["instance-single"]),
            ("a = AlertConfiguration._meta.concrete_model._meta.model.objects.create(team=t)", ["write(create)"]),
            ("m = AlertConfiguration._meta.model", ["_meta"]),
            ("s = AlertConfiguration._meta.model.Status.FIRING", ["nested-class-attr(Status)"]),
            ("m = AlertConfiguration._meta.managers", ["other(Attribute:_meta.managers)"]),
            ("by_id = AlertConfiguration.objects.in_bulk(ids)", ["instance-many(in_bulk)"]),
            ("a = AlertConfiguration.objects.filter(team=t).first()", ["instance-single"]),
            ("qs = AlertConfiguration.objects.filter(team=t)", ["instance-many(filter)"]),
            ("qs = AlertConfiguration.objects", ["instance-many(manager)"]),
            ("qs = AlertConfiguration.objects.all().select_related('insight')", ["instance-many(select_related)"]),
            ("p = Prefetch('alerts', queryset=AlertConfiguration.objects.filter(team=t))", ["prefetch"]),
            ("f = PrimaryKeyRelatedField(queryset=AlertConfiguration.objects.all())", ["drf-field-queryset"]),
            ("class Meta:\n    model = AlertConfiguration", ["drf-model-serializer"]),
            ("if isinstance(obj, AlertConfiguration):\n    pass", ["isinstance"]),
            ("a = cast(AlertConfiguration, obj)", ["passed-as-class(cast)"]),
            ("REGISTRY = (AlertConfiguration, None)", ["in-collection"]),
            ("a = AlertConfiguration(team=t)", ["construct"]),
            ("a = AlertConfiguration.objects.create(team=t)", ["write(create)"]),
            ("AlertConfiguration.objects.filter(team=t).update(enabled=False)", ["write(update)"]),
            ("a = AlertConfiguration.objects.select_for_update().get(pk=1)", ["lock"]),
            ("qs = AlertConfiguration.objects.select_for_update().filter(team=t)", ["lock"]),
            ("p = Prefetch('a', queryset=AlertConfiguration.objects.select_related('insight'))", ["prefetch"]),
            ("v = AlertConfiguration.compute_condition_type(x)", ["other(Attribute:compute_condition_type)"]),
            ("x = AlertConfiguration if flag else None", ["other(IfExp)"]),
        ],
    )
    def test_kind(self, body: str, expected: list[str]) -> None:
        assert classify(IMPORT + textwrap.dedent(body)) == expected

    @pytest.mark.parametrize(
        "kind,allowed",
        [
            ("annotation", True),
            ("scalar-chain(values_list)", True),
            ("subquery(Exists)", True),
            ("instance-single", False),
            ("prefetch", False),
            ("write(create)", False),
            ("other(IfExp)", False),
        ],
    )
    def test_allowed_split(self, kind: str, allowed: bool) -> None:
        assert kind_is_allowed(kind) is allowed


class TestBindingPaths:
    @pytest.mark.parametrize(
        "source",
        [
            "from products.alerts.backend.models.alert import AlertConfiguration as AC\nqs = AC.objects.filter(t=1)",
            "if TYPE_CHECKING:\n    from products.alerts.backend.models.alert import AlertConfiguration\nqs = AlertConfiguration.objects.filter(t=1)",
            "def f():\n    from products.alerts.backend.models.alert import AlertConfiguration\n    return AlertConfiguration.objects.filter(t=1)",
            "from products.alerts.backend.models.alert import (\n    AlertConfiguration,\n    Threshold,\n)\nqs = AlertConfiguration.objects.filter(t=1)",
            "from products.alerts.backend.models import alert\nqs = alert.AlertConfiguration.objects.filter(t=1)",
            "from products.alerts.backend.models import alert as alert_models\nqs = alert_models.AlertConfiguration.objects.filter(t=1)",
            "import products.alerts.backend.models.alert\nqs = products.alerts.backend.models.alert.AlertConfiguration.objects.filter(t=1)",
            "import products.alerts.backend.models.alert as alert_models\nqs = alert_models.AlertConfiguration.objects.filter(t=1)",
        ],
    )
    def test_every_import_shape_binds(self, source: str) -> None:
        assert classify(source) == ["instance-many(filter)"]

    def test_reexport_chain_resolves_to_the_defining_module(self) -> None:
        facade = _candidate(
            "from ..models.alert import AlertConfiguration as AlertConfiguration",
            "products.alerts.backend.facade.models",
        )
        consumer = _candidate(
            "from products.alerts.backend.facade.models import AlertConfiguration\n"
            "a = AlertConfiguration.objects.get(pk=1)"
        )
        origins = crossings._origins([facade, consumer], [ALERT])
        assert crossings._bound_names(consumer, origins) == {"AlertConfiguration": "alerts.AlertConfiguration"}

    def test_unrelated_class_of_the_same_name_is_not_bound(self) -> None:
        candidate = _candidate(
            "from products.alerts.backend.facade.contracts import AlertConfiguration\nqs = AlertConfiguration(id=1)"
        )
        origins = crossings._origins([candidate], [ALERT])
        assert crossings._bound_names(candidate, origins) == {}


class TestGetModelStrings:
    @pytest.mark.parametrize(
        "call",
        [
            "apps.get_model('alerts', 'AlertConfiguration')",
            "apps.get_model('alerts.AlertConfiguration')",
            "apps.get_model('alerts', model_name='AlertConfiguration')",
            "apps.get_model(app_label='alerts', model_name='AlertConfiguration')",
            "apps.get_model(model_name='AlertConfiguration', app_label='alerts')",
            "apps.get_model('alerts', 'alertconfiguration')",
            "apps.get_model('alerts.ALERTCONFIGURATION')",
        ],
    )
    def test_every_string_form_is_counted(self, call: str) -> None:
        tree = ast.parse(f"m = {call}")
        found = crossings._get_model_uses(tree, {"alerts": "alerts"}, LOOKUP)
        assert found == {"alerts.AlertConfiguration": 1}

    def test_unlisted_class_is_ignored(self) -> None:
        tree = ast.parse("m = apps.get_model('alerts', 'AlertCheck')")
        assert crossings._get_model_uses(tree, {"alerts": "alerts"}, LOOKUP) == {}

    def test_unknown_app_label_is_ignored(self) -> None:
        tree = ast.parse("m = apps.get_model('posthog', 'AlertConfiguration')")
        assert crossings._get_model_uses(tree, {"alerts": "alerts"}, LOOKUP) == {}


class TestProductModelLabels:
    @pytest.mark.parametrize(
        "label,product",
        [
            # The first two are off MODEL_CROSSINGS, and cover the two model-surface shapes the
            # scan has to walk: a models package, and a flat models.py.
            ("alerts.AlertConfiguration", "alerts"),
            ("error_tracking.ErrorTrackingIssue", "error_tracking"),
            ("product_analytics.Insight", "product_analytics"),
        ],
    )
    def test_model_surface_classes_resolve_to_their_product(self, label: str, product: str) -> None:
        assert crossings.product_model_labels().get(label) == product

    def test_products_filter_keeps_only_the_named_product(self) -> None:
        labels = crossings.product_model_labels(["alerts"])
        assert labels and set(labels.values()) == {"alerts"}

    def test_baseline_never_records_a_products_own_get_model_calls(self) -> None:
        own = []
        for line in crossings.read_baseline():
            crossing, consumer, kind, _ = line.split()
            owner = crossing.split(".")[0]
            if kind == "get_model" and consumer.startswith(f"products.{owner}."):
                own.append(line)
        assert own == []


class TestRenderReport:
    def test_allowed_counts_sum_across_modules(self) -> None:
        uses = [
            crossings.CrossingUse("alerts.AlertConfiguration", "posthog.api.a", "annotation", 1),
            crossings.CrossingUse("alerts.AlertConfiguration", "posthog.api.b", "annotation", 2),
        ]
        assert "allowed: annotation 3" in crossings.render_report(uses)


DISPATCHER = """
def get_query_runner(query, team, kind=None):
    if kind == "TrendsQuery":
        from .insights.trends.trends_query_runner import TrendsQueryRunner

        return TrendsQueryRunner(query=query, team=team)
    if kind == "PathsQuery":
        from products.product_analytics.backend.facade.queries import PathsQueryRunner

        return PathsQueryRunner(query=query, team=team)
    if kind in ("WebOverviewQuery", "WebStatsTableQuery"):
        from products.web_analytics.backend.hogql_queries.web_overview import WebOverviewQueryRunner

        return WebOverviewQueryRunner(query=query, team=team)
    if kind == NodeKind.MARKETING_ANALYTICS_TABLE_QUERY:
        from products.marketing_analytics.backend.hogql_queries.table import MarketingAnalyticsTableQueryRunner

        return MarketingAnalyticsTableQueryRunner(query=query, team=team)
    if kind == "TrendsQuery":
        if query.tags and query.tags.productKey == "web_analytics":
            from products.web_analytics.backend.hogql_queries.web_trends import WebTrendsQueryRunner

            return WebTrendsQueryRunner(query=query, team=team)
        from .insights.trends.trends_query_runner import TrendsQueryRunner

        return TrendsQueryRunner(query=query, team=team)
"""

NODE_KIND_ENUM = """
class OtherEnum(StrEnum):
    X = "NotAKind"


class NodeKind(StrEnum):
    EVENTS_NODE = "EventsNode"
    MARKETING_ANALYTICS_TABLE_QUERY = "MarketingAnalyticsTableQuery"


class After(StrEnum):
    Y = "AlsoNotAKind"
"""

KINDS = crossings._QueryKinds(
    {"PathsQuery": frozenset({"product_analytics"}), "WebOverviewQuery": frozenset({"web_analytics"})},
    {"PATHS_QUERY": "PathsQuery"},
)


class TestGarageDrives:
    def test_dispatch_table_maps_product_kinds_only(self) -> None:
        node_kinds = crossings._node_kind_values(NODE_KIND_ENUM)
        assert node_kinds == {
            "EVENTS_NODE": "EventsNode",
            "MARKETING_ANALYTICS_TABLE_QUERY": "MarketingAnalyticsTableQuery",
        }
        assert crossings._kinds_in_dispatcher(DISPATCHER, node_kinds) == {
            "PathsQuery": frozenset({"product_analytics"}),
            "WebOverviewQuery": frozenset({"web_analytics"}),
            "WebStatsTableQuery": frozenset({"web_analytics"}),
            "MarketingAnalyticsTableQuery": frozenset({"marketing_analytics"}),
            # a core kind that hands off to a product under a nested condition reaches that product
            "TrendsQuery": frozenset({"web_analytics"}),
        }

    @pytest.mark.parametrize(
        "source, expected",
        [
            # a kind literal handed to the dispatcher is a drive
            (
                """
                def test_paths(team):
                    process_query_dict(team, {"kind": "PathsQuery", "pathsFilter": {}})
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # the schema constructor run through the dispatcher is a drive too
            (
                """
                def test_paths(team):
                    get_query_runner(PathsQuery(pathsFilter={}), team).calculate()
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # a fixture built in setUp and executed over the in-process test client, same class
            (
                """
                class TestInsights(APIBaseTest):
                    def setUp(self):
                        self.query = {"kind": "PathsQuery"}

                    def test_run(self):
                        self.client.post("/api/projects/1/query/", {"query": self.query})
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # built and never run: a schema or formatter check, not a drive
            (
                """
                def test_metadata():
                    assert extract(PathsQuery(pathsFilter={})).kind == "PathsQuery"
                """,
                {},
            ),
            # a parametrize row that flows into the dispatcher is a drive
            (
                """
                class TestKinds(TestCase):
                    @parameterized.expand([("PathsQuery",), ("TrendsQuery",)])
                    def test_runs(self, kind):
                        process_query_dict(self.team, {"kind": kind})
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # a test that reaches the client through two helpers still executes
            (
                """
                class TestChain(APIBaseTest):
                    def _post(self, body):
                        return self.client.post("/api/projects/1/query/", body)

                    def _run(self, query):
                        return self._post({"query": query})

                    def test_paths(self):
                        assert self._run({"kind": "PathsQuery"}).status_code == 200
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # a method that runs the kind through a module-level helper executes too
            (
                """
                def post_query(client, query):
                    return client.post("/api/projects/1/query/", {"query": query})

                class TestPaths(APIBaseTest):
                    def test_paths(self):
                        assert post_query(self.client, {"kind": "PathsQuery"}).status_code == 200
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # a helper inherited from a base class in the same module executes too
            (
                """
                class QueryTestBase(APIBaseTest):
                    def run_query(self, query):
                        return self.client.post("/api/projects/1/query/", {"query": query})

                class TestPaths(QueryTestBase):
                    def test_paths(self):
                        assert self.run_query({"kind": "PathsQuery"}).status_code == 200
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # a HogQL string that embeds the kind in tag syntax and runs through the executor
            (
                """
                class TestActors(ClickhouseTestMixin, APIBaseTest):
                    def select(self, query):
                        return execute_hogql_query(query=query, team=self.team)

                    def test_stickiness_actors(self):
                        hogql = "select * from (<InsightActorsQuery day={2}><PathsQuery series={[]} /></InsightActorsQuery>)"
                        assert self.select(hogql).results
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # two bases define the helper; the one that executes wins whatever the order
            (
                """
                class Quiet(TestCase):
                    def _run(self, query):
                        return query

                class Posting(APIBaseTest):
                    def _run(self, query):
                        return self.client.post("/api/projects/1/query/", {"query": query})

                class TestPaths(Quiet, Posting):
                    def test_paths(self):
                        assert self._run({"kind": "PathsQuery"})
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # a bare string in a test that never executes, or a URL segment, is not a drive
            (
                """
                class TestTags(TestCase):
                    @parameterized.expand([("PathsQuery",), ("TrendsQuery",)])
                    def test_tags(self, kind):
                        assert tag_for(kind)

                    def test_other(self):
                        self.client.get("/api/projects/1/query/PathsQuery/")
                """,
                {},
            ),
            # a test method that only builds the kind is not a drive, whatever its siblings run
            (
                """
                class TestEndpoints(APIBaseTest):
                    @parameterized.expand([("paths", {"kind": "PathsQuery"})])
                    def test_rejects(self, _name, query):
                        assert not can_materialize(query)

                    def test_materializes(self):
                        self.client.patch("/api/projects/1/endpoints/x/", {"is_materialized": True})
                """,
                {},
            ),
            # a test method that runs the kind through a helper of its own is a drive
            (
                """
                class TestPaths(APIBaseTest):
                    def _run(self, query):
                        return self.client.post("/api/projects/1/query/", {"query": query})

                    def test_paths(self):
                        assert self._run({"kind": "PathsQuery"}).status_code == 200
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # the enum form of a kind counts like the literal
            (
                """
                def test_paths(team):
                    process_query_dict(team, {"kind": NodeKind.PATHS_QUERY, "pathsFilter": {}})
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # a same-named method in a later class does not answer for the one that executes
            (
                """
                class TestRuns(APIBaseTest):
                    def test_paths(self):
                        self.client.post("/api/projects/1/query/", {"query": {"kind": "PathsQuery"}})

                class TestBuilds(TestCase):
                    def test_paths(self):
                        assert {"kind": "PathsQuery"}["kind"]
                """,
                {("product_analytics", "PathsQuery"): 1},
            ),
            # execution in another class does not count for this class's fixture
            (
                """
                class TestBuild(TestCase):
                    def test_build(self):
                        assert {"kind": "PathsQuery"}["kind"]

                class TestRun(APIBaseTest):
                    def test_run(self):
                        self.client.post("/api/projects/1/query/", {"query": {"kind": "TrendsQuery"}})
                """,
                {},
            ),
            # a core kind is never a drive, and two products are told apart
            (
                """
                def test_both(team):
                    process_query_dict(team, {"kind": "TrendsQuery"})
                    process_query_dict(team, {"kind": "WebOverviewQuery"})
                    process_query_dict(team, {"kind": "WebOverviewQuery"})
                """,
                {("web_analytics", "WebOverviewQuery"): 2},
            ),
        ],
    )
    def test_kind_drives(self, source: str, expected: dict[tuple[str, str], int]) -> None:
        drives = crossings.kind_drives(ast.parse(textwrap.dedent(source)), KINDS)
        assert {(drive.product, drive.kind): count for drive, count in drives.items()} == expected

    def test_lazy_facade_map_resolves_to_its_source_module(self) -> None:
        facade = textwrap.dedent(
            """
            _B = "products.product_analytics.backend.hogql_queries."
            _LAZY = {"PathsQueryRunner": "paths.paths_query_runner", "helper": "logic.helpers"}

            def __getattr__(name):
                return None
            """
        )
        existing = {
            "products.product_analytics.backend.hogql_queries.paths.paths_query_runner",
            "products.product_analytics.backend.logic.helpers",
        }
        assert crossings._lazy_reexports(ast.parse(facade), "product_analytics", existing.__contains__) == {
            "PathsQueryRunner": "products.product_analytics.backend.hogql_queries.paths.paths_query_runner",
            "helper": "products.product_analytics.backend.logic.helpers",
        }

    def test_top_level_names_include_constants(self) -> None:
        module = "BOT_DEFINITIONS = [...]\nLIMIT: int = 5\n_private = 1\n\nclass Runner: ...\n\ndef helper(): ...\n"
        assert crossings._top_level_names(ast.parse(module)) == ["BOT_DEFINITIONS", "LIMIT", "Runner", "helper"]

    def test_aliased_constructor_counts_by_its_kind(self) -> None:
        source = textwrap.dedent(
            """
            from posthog.schema import PathsQuery as Query

            def test_paths(team):
                get_query_runner(Query(pathsFilter={}), team).calculate()
            """
        )
        imports = crossings._read_imports(source.encode(), "posthog.test")
        names = crossings._kind_names(imports, KINDS)
        assert names.constructors == {"Query": "PathsQuery"}
        drives = crossings.kind_drives(ast.parse(source), KINDS, names)
        assert {(d.product, d.kind): n for d, n in drives.items()} == {("product_analytics", "PathsQuery"): 1}
        assert crossings._KindHint.for_kinds(KINDS).matches(source.encode())

    def test_aliased_enum_counts_by_its_kind(self) -> None:
        source = textwrap.dedent(
            """
            from posthog.schema import NodeKind as Kind

            def test_paths(team):
                process_query_dict(team, {"kind": Kind.PATHS_QUERY})
            """
        )
        imports = crossings._read_imports(source.encode(), "posthog.test")
        names = crossings._kind_names(imports, KINDS)
        assert names.enum_bases == frozenset({"Kind", "NodeKind"})
        drives = crossings.kind_drives(ast.parse(source), KINDS, names)
        assert {(d.product, d.kind): n for d, n in drives.items()} == {("product_analytics", "PathsQuery"): 1}
        assert crossings._KindHint.for_kinds(KINDS).matches(source.encode())

    def test_member_off_an_unrelated_base_is_not_a_kind(self) -> None:
        source = textwrap.dedent(
            """
            from elsewhere import Other as Kind

            def test_paths(team):
                process_query_dict(team, {"kind": Kind.PATHS_QUERY})
            """
        )
        imports = crossings._read_imports(source.encode(), "posthog.test")
        names = crossings._kind_names(imports, KINDS)
        assert names.enum_bases == frozenset({"NodeKind"})
        assert crossings.kind_drives(ast.parse(source), KINDS, names) == {}

    def test_package_qualified_enum_counts_by_its_kind(self) -> None:
        source = textwrap.dedent(
            """
            from posthog import schema

            def test_paths(team):
                process_query_dict(team, {"kind": schema.NodeKind.PATHS_QUERY})
            """
        )
        names = crossings._kind_names(crossings._read_imports(source.encode(), "posthog.test"), KINDS)
        drives = crossings.kind_drives(ast.parse(source), KINDS, names)
        assert {(d.product, d.kind): n for d, n in drives.items()} == {("product_analytics", "PathsQuery"): 1}

    def test_enum_member_value_counts_once(self) -> None:
        source = textwrap.dedent(
            """
            from posthog.schema import NodeKind

            def test_paths(team):
                process_query_dict(team, {"kind": NodeKind.PATHS_QUERY.value})
            """
        )
        names = crossings._kind_names(crossings._read_imports(source.encode(), "posthog.test"), KINDS)
        drives = crossings.kind_drives(ast.parse(source), KINDS, names)
        assert {(d.product, d.kind): n for d, n in drives.items()} == {("product_analytics", "PathsQuery"): 1}

    def test_aliased_dispatcher_still_executes(self) -> None:
        source = textwrap.dedent(
            """
            from posthog.schema import PathsQuery
            from posthog.api.services.query import process_query_dict as run_query

            def test_paths(team):
                run_query(team, PathsQuery(pathsFilter={}))
            """
        )
        imports = crossings._read_imports(source.encode(), "posthog.test")
        names = crossings._kind_names(imports, KINDS)
        assert "run_query" in names.dispatchers
        drives = crossings.kind_drives(ast.parse(source), KINDS, names)
        assert {(d.product, d.kind): n for d, n in drives.items()} == {("product_analytics", "PathsQuery"): 1}

    def test_every_node_kind_enum_is_read(self) -> None:
        source = textwrap.dedent(
            """
            class InsightNodeKind(StrEnum):
                PATHS_QUERY = "PathsQuery"


            class NodeKind(StrEnum):
                EVENTS_NODE = "EventsNode"
            """
        )
        assert set(crossings._node_kind_enums(source)) == {"InsightNodeKind", "NodeKind"}
        assert crossings._node_kind_values(source) == {"PATHS_QUERY": "PathsQuery", "EVENTS_NODE": "EventsNode"}

    def test_module_object_imports_count_as_drives(self) -> None:
        source = textwrap.dedent(
            """
            import products.web_analytics.backend.hogql_queries.web_overview as overview
            from products.web_analytics.backend.hogql_queries import stats_table
            from products.web_analytics.backend.facade.queries import WebOverviewQueryRunner
            """
        )
        imports = crossings._read_imports(source.encode(), "posthog.test")
        location = crossings._WiringLocation("web_analytics", "backend/hogql_queries/")
        modules = {
            "products.web_analytics.backend.hogql_queries.web_overview",
            "products.web_analytics.backend.hogql_queries.stats_table",
        }
        assert crossings.module_drives(imports, [location], modules.__contains__) == {
            crossings._ModuleDrive(location.label, "web_overview"): 1,
            crossings._ModuleDrive(location.label, "stats_table"): 1,
        }

    def test_hint_matches_the_enum_form(self) -> None:
        hint = crossings._KindHint.for_kinds(KINDS)
        assert hint.matches(b'client.post(url, {"query": {"kind": NodeKind.PATHS_QUERY}})')
        assert not hint.matches(b"NodeKind.TRENDS_QUERY")

    def test_driven_wiring_locations_reads_the_products_lines(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline.txt"
        baseline.write_text(
            "# header\n"
            "product_analytics:backend/hogql_queries/ posthog.api.test.test_x drives(PathsQuery) 1\n"
            "product_analytics.Insight posthog.api.sharing instance-many(all) 1\n"
            "web_analytics:backend/hogql_queries/ posthog.test.test_y drives(WebOverviewQueryRunner) 1\n"
        )
        assert crossings.driven_wiring_locations("product_analytics", baseline) == {"backend/hogql_queries/"}
        assert crossings.driven_wiring_locations("error_tracking", baseline) == frozenset()


class TestUnresolvedKindDrives:
    """The floor under the spellings `_kind_of` reads: a kind the scan cannot read still counts."""

    @staticmethod
    def _count(body: str) -> int:
        source = textwrap.dedent(body)
        names = crossings._kind_names(crossings._read_imports(source.encode(), "posthog.test"), KINDS)
        return crossings.unresolved_kind_drives(ast.parse(source), KINDS, names)

    def test_unreadable_kind_reaching_a_dispatcher_counts(self) -> None:
        assert (
            self._count(
                """
                from posthog.api.services.query import process_query_dict

                def test_paths(team, kind):
                    process_query_dict(team, {"kind": kind})
                """
            )
            == 1
        )

    def test_unreadable_kind_posted_to_the_client_counts(self) -> None:
        assert (
            self._count(
                """
                class TestPaths:
                    def test_paths(self):
                        self.client.post("/api/environments/1/query/", {"query": {"kind": self.kind}})
                """
            )
            == 1
        )

    @parameterized.expand(
        [
            ("a kind the scan reads", '{"kind": "PathsQuery"}'),
            ("a kind that belongs to no product", '{"kind": "EventsQuery"}'),
            ("an enum member", '{"kind": NodeKind.PATHS_QUERY}'),
        ]
    )
    def test_a_readable_kind_does_not_count(self, _name: str, payload: str) -> None:
        assert (
            self._count(
                f"""
                from posthog.schema import NodeKind
                from posthog.api.services.query import process_query_dict

                def test_paths(team):
                    process_query_dict(team, {payload})
                """
            )
            == 0
        )

    def test_a_scope_that_names_a_kind_does_not_count(self) -> None:
        """A parametrized test names its kinds in the decorator, which stands as the evidence."""
        assert (
            self._count(
                """
                from posthog.api.services.query import process_query_dict

                @parameterized.expand([("PathsQuery",)])
                def test_paths(team, kind):
                    process_query_dict(team, {"kind": kind})
                """
            )
            == 0
        )

    def test_a_constant_default_is_readable(self) -> None:
        assert (
            self._count(
                """
                from posthog.api.services.query import process_query_dict

                def test_paths(team, kind="DataTableNode"):
                    process_query_dict(team, {"kind": kind})
                """
            )
            == 0
        )

    def test_a_kind_that_never_executes_does_not_count(self) -> None:
        assert (
            self._count(
                """
                def test_paths(kind):
                    payload = {"query": {"kind": kind}}
                    assert payload["query"]["kind"] == kind
                """
            )
            == 0
        )

    def test_an_unrelated_kind_key_does_not_count(self) -> None:
        """`kind` names many things; only a dict in query position is a query."""
        assert (
            self._count(
                """
                class TestEmail:
                    def test_email(self):
                        self.client.post("/api/environments/1/query/", {"kind": self.channel.kind})
                """
            )
            == 0
        )
