"""Tests for the model-crossing use classifier."""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

import pytest

from hogli_commands.product import crossings
from hogli_commands.product.crossings import CrossingClass, classify_use, kind_is_allowed

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

KINDS = {"PathsQuery": "product_analytics", "WebOverviewQuery": "web_analytics"}


class TestGarageDrives:
    def test_dispatch_table_maps_product_kinds_only(self) -> None:
        node_kinds = crossings._node_kind_values(NODE_KIND_ENUM)
        assert node_kinds == {
            "EVENTS_NODE": "EventsNode",
            "MARKETING_ANALYTICS_TABLE_QUERY": "MarketingAnalyticsTableQuery",
        }
        assert crossings._kinds_in_dispatcher(DISPATCHER, node_kinds) == {
            "PathsQuery": "product_analytics",
            "WebOverviewQuery": "web_analytics",
            "WebStatsTableQuery": "web_analytics",
            "MarketingAnalyticsTableQuery": "marketing_analytics",
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
            # a bare string is a parametrize row or a URL segment, not a query
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

    def test_driven_garages_reads_the_products_lines(self, tmp_path: Path) -> None:
        baseline = tmp_path / "baseline.txt"
        baseline.write_text(
            "# header\n"
            "product_analytics:backend/hogql_queries/ posthog.api.test.test_x drives(PathsQuery) 1\n"
            "product_analytics.Insight posthog.api.sharing instance-many(all) 1\n"
            "web_analytics:backend/hogql_queries/ posthog.test.test_y drives(WebOverviewQueryRunner) 1\n"
        )
        assert crossings.driven_wiring_locations("product_analytics", baseline) == {"backend/hogql_queries/"}
        assert crossings.driven_wiring_locations("error_tracking", baseline) == frozenset()
