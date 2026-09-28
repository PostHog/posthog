from __future__ import annotations

import json
from pathlib import Path

import pytest

import yaml
from click.testing import CliRunner, Result
from hogli_commands import api_ratchet
from hogli_commands.api_ratchet import ApiRequestResolver, Ratchet, cmd_lint_api_ratchet, read_baseline
from parameterized import parameterized

runner = CliRunner()

API_TS_FIXTURE = """\
export class ApiRequest {
    private addPathComponent(component: string | number): ApiRequest {
        this.pathComponents.push(component.toString())
        return this
    }

    public organizations(): ApiRequest {
        return this.addPathComponent('organizations')
    }

    public current(): ApiRequest {
        return this.addPathComponent('@current')
    }

    public organizationMembers(): ApiRequest {
        return this.organizations().current().addPathComponent('members')
    }

    public projects(): ApiRequest {
        return this.addPathComponent('projects')
    }

    public projectsDetail(id: ProjectType['id'] = ApiConfig.getCurrentProjectId()): ApiRequest {
        return this.projects().addPathComponent(id)
    }

    public environmentsDetail(id: TeamType['id'] = ApiConfig.getCurrentTeamId()): ApiRequest {
        return this.environments().addPathComponent(id)
    }

    public signalReports(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('signals').addPathComponent('reports')
    }

    public signalReport(id: SignalReport['id'], teamId?: TeamType['id']): ApiRequest {
        return this.signalReports(teamId).addPathComponent(id)
    }

    public propertyDefinitions(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('property_definitions')
    }

    public signalReportSimilar(id: SignalReport['id'], teamId?: TeamType['id']): ApiRequest {
        return this.signalReports(teamId).addPathComponent(`${id}/similar`)
    }

    public signalReportChecks(id?: string, teamId?: TeamType['id']): ApiRequest {
        let request = this.signalReports(teamId).addPathComponent('checks')
        if (id) {
            request = request.addPathComponent(id)
            return request
        }
        return request
    }

    public signalScoutRuns(kind?: string, teamId?: TeamType['id']): ApiRequest {
        const request = this.projectsDetail(teamId).addPathComponent('signals')
        if (!kind) {
            return request
        }
        request.addPathComponent('scout')
        return request.addPathComponent(kind)
    }

    public hogFlows(): ApiRequest {
        return this.environmentsDetail().addPathComponent('hog_flows')
    }

    public errorTrackingStackFrames(): ApiRequest {
        return this.errorTracking().addPathComponent('stack_frames/batch_get')
    }

    public errorTracking(teamId?: TeamType['id']): ApiRequest {
        return this.environmentsDetail(teamId).addPathComponent('error_tracking')
    }

    public alerts(alertId?: AlertType['id'], teamId?: TeamType['id']): ApiRequest {
        if (alertId) {
            return this.environmentsDetail(teamId).addPathComponent('alerts').addPathComponent(alertId)
        }
        return this.environmentsDetail(teamId).addPathComponent('alerts')
    }

    public alert(alertId: AlertType['id']): ApiRequest {
        return this.alerts(alertId)
    }

    public alertsCollection(): ApiRequest {
        return this.alerts()
    }

    public query(teamId?: TeamType['id'], queryKind?: string): ApiRequest {
        const apiRequest = this.environmentsDetail(teamId).addPathComponent('query')
        if (queryKind) {
            return apiRequest.addPathComponent(queryKind)
        }
        return apiRequest
    }

    // A mutation that falls through - no return of its own inside the `if` - leaves
    // the shared return below reachable whether or not the block ran.
    public signalReportArchive(archived?: boolean, teamId?: TeamType['id']): ApiRequest {
        const request = this.signalReports(teamId).addPathComponent('archive')
        if (archived) {
            request.addPathComponent('archived')
        }
        return request
    }

    // No `public` keyword - TypeScript makes this callable from `api` regardless.
    signalReportPin(id: SignalReport['id'], teamId?: TeamType['id']): ApiRequest {
        return this.signalReport(id, teamId).addPathComponent('pin')
    }

    public async get(): Promise<any> {
        return await api.get(this.assembleFullUrl())
    }
}

const api = {
    signalReports: {
        async list(): Promise<any> {
            return await new ApiRequest().signalReports().get()
        },
    },
    hogFlows: {
        async list(): Promise<any> {
            return await new ApiRequest().hogFlows().get()
        },
    },
    comments: {
        async list(): Promise<any> {
            return await new ApiRequest().comments().get()
        },
    },
    propertyDefinitions: {
        async list(): Promise<any> {
            return await new ApiRequest().propertyDefinitions().get()
        },
    },
}
"""

GENERATED_SIGNALS = """\
export const signalsReportsList = (projectId: string) => {
    return apiMutator({ url: `/api/projects/${projectId}/signals/reports/`, method: 'GET' })
}
export const signalsReportsRetrieve = (projectId: string, id: string) => {
    return apiMutator({ url: `/api/projects/${projectId}/signals/reports/${id}/`, method: 'GET' })
}
"""

GENERATED_WORKFLOWS = """\
export const hogFlowsList = (projectId: string) => {
    return apiMutator({ url: `/api/projects/${projectId}/hog_flows/`, method: 'GET' })
}
"""

GENERATED_CORE = """\
export const propertyDefinitionsList = (projectId: string) => {
    return apiMutator({ url: `/api/projects/${projectId}/property_definitions/`, method: 'GET' })
}
export const organizationMembersList = (organizationId: string) => {
    return apiMutator({ url: `/api/organizations/${organizationId}/members/`, method: 'GET' })
}
export const remindersList = () => {
    return apiMutator({ url: `/api/reminders/`, method: 'GET' })
}
"""


def _write_repo(
    root: Path,
    api_ts: str = API_TS_FIXTURE,
    baseline: str | None = None,
    generated_signals: str = GENERATED_SIGNALS,
    generated_workflows: str = GENERATED_WORKFLOWS,
) -> None:
    (root / "frontend/src/lib").mkdir(parents=True, exist_ok=True)
    (root / "frontend/src/lib/api.ts").write_text(api_ts)
    (root / "products/signals/frontend/generated").mkdir(parents=True, exist_ok=True)
    (root / "products/signals/frontend/generated/api.ts").write_text(generated_signals)
    (root / "products/workflows/frontend/generated").mkdir(parents=True, exist_ok=True)
    (root / "products/workflows/frontend/generated/api.ts").write_text(generated_workflows)
    (root / api_ratchet.CORE_GENERATED).parent.mkdir(parents=True, exist_ok=True)
    (root / api_ratchet.CORE_GENERATED).write_text(GENERATED_CORE)
    rule = root / api_ratchet.SEMGREP_RULE
    rule.parent.mkdir(parents=True, exist_ok=True)
    rule.write_text(f"rules:\n{api_ratchet.SEMGREP_BEGIN}\n{api_ratchet.SEMGREP_END}\n")
    api_ratchet.write_semgrep_rules(root, Ratchet(root))
    if baseline is not None:
        (root / api_ratchet.BASELINE).write_text(baseline)


# Baseline lines carry the route, so the fixtures build them from the resolver.
_FIXTURE_ROUTES = {
    "signalReports": "projects/{}/signals/reports",
    "signalReport": "projects/{}/signals/reports/{}",
    "hogFlows": "projects/{}/hog_flows",
    "propertyDefinitions": "projects/{}/property_definitions",
    "organizationMembers": "organizations/{}/members",
}


def _baseline_lines(*names: str) -> str:
    return "".join(f"{name} {_FIXTURE_ROUTES[name]}\n" for name in names)


# A base ref where `hogFlows` never existed.
API_TS_FIXTURE_WITHOUT_HOGFLOWS = API_TS_FIXTURE.replace(
    "    public hogFlows(): ApiRequest {\n        return this.environmentsDetail().addPathComponent('hog_flows')\n    }\n\n",
    "",
)


class TestApiRequestResolver:
    @parameterized.expand(
        [
            ("literal chain off projectsDetail", "signalReports", ["projects/{}/signals/reports"]),
            # The prototype collapsed the whole template literal to one hole, which
            # resolved this to the detail route and called it covered.
            (
                "a template literal keeps its literal segments",
                "signalReportSimilar",
                ["projects/{}/signals/reports/{}/similar"],
            ),
            # organizations().current() passes through another path method, and reading
            # only the component builders dropped the @current segment.
            (
                "a chain through a path helper keeps its segments",
                "organizationMembers",
                ["organizations/@current/members"],
            ),
            # The mutation inside the `if` must not reach the return below the block,
            # or the collection route disappears.
            (
                "a conditional mutation stays inside its branch",
                "signalReportChecks",
                ["projects/{}/signals/reports/checks/{}", "projects/{}/signals/reports/checks"],
            ),
            # The second return reads a chain the first branch did not see.
            (
                "a mutation between two returns reaches the later one",
                "signalScoutRuns",
                ["projects/{}/signals", "projects/{}/signals/scout/{}"],
            ),
            ("dynamic component becomes a hole", "signalReport", ["projects/{}/signals/reports/{}"]),
            ("environments alias is kept until normalization", "hogFlows", ["environments/{}/hog_flows"]),
            (
                "a literal holding a slash splits into segments",
                "errorTrackingStackFrames",
                ["environments/{}/error_tracking/stack_frames/batch_get"],
            ),
            (
                "both branches of a conditional resolve",
                "alerts",
                ["environments/{}/alerts/{}", "environments/{}/alerts"],
            ),
            # `alert` always forwards a required id, so the no-id branch is unreachable.
            (
                "a required argument rules out the branch that doesn't consume it",
                "alert",
                ["environments/{}/alerts/{}"],
            ),
            # `alertsCollection` forwards nothing, so the id branch is unreachable.
            (
                "no argument rules out the branch that needs one",
                "alertsCollection",
                ["environments/{}/alerts"],
            ),
            # The chain root lives in the body, not in the return statement. Resolving
            # the return alone drops environments/{} and the URL looks like /api/query.
            (
                "a chain assigned to a local keeps its root",
                "query",
                ["environments/{}/query/{}", "environments/{}/query"],
            ),
            ("the root path method resolves to its own segment", "projects", ["projects"]),
            # `archived` only mutates and falls through - no return of its own inside
            # the `if` - so the shared return below is reachable either way.
            (
                "a mutation that falls through resolves both ways",
                "signalReportArchive",
                ["projects/{}/signals/reports/archive", "projects/{}/signals/reports/archive/archived"],
            ),
            (
                "a method without the `public` keyword still resolves",
                "signalReportPin",
                ["projects/{}/signals/reports/{}/pin"],
            ),
        ]
    )
    def test_resolves(self, _name: str, method: str, expected: list[str]) -> None:
        resolver = ApiRequestResolver(API_TS_FIXTURE)
        assert ["/".join(template) for template in resolver.templates(method)] == expected

    def test_verb_methods_are_not_path_methods(self) -> None:
        # `get` returns a Promise, so counting it would give every namespace a bare
        # /api/projects/{} template and match half the generated output.
        assert "get" not in ApiRequestResolver(API_TS_FIXTURE).method_names()

    def test_method_names_include_methods_without_public_keyword(self) -> None:
        assert "signalReportPin" in ApiRequestResolver(API_TS_FIXTURE).method_names()


class TestRatchet:
    def test_flags_methods_with_a_generated_twin(self, tmp_path: Path) -> None:
        _write_repo(tmp_path)
        assert {entry.entry: sorted(entry.products) for entry in Ratchet(tmp_path).redundant} == {
            "signalReports projects/{}/signals/reports": ["signals"],
            "signalReport projects/{}/signals/reports/{}": ["signals"],
            "hogFlows projects/{}/hog_flows": ["workflows"],
            "propertyDefinitions projects/{}/property_definitions": ["core"],
            "organizationMembers organizations/{}/members": ["core"],
        }

    def test_namespaces_lists_only_those_calling_a_redundant_method(self, tmp_path: Path) -> None:
        _write_repo(tmp_path)
        assert {ns: sorted(products) for ns, products in Ratchet(tmp_path).namespaces().items()} == {
            "signalReports": ["signals"],
            "hogFlows": ["workflows"],
        }

    def test_namespaces_drops_the_core_sentinel(self, tmp_path: Path) -> None:
        # `propertyDefinitions` is redundant only against the core client, and CORE_OWNER
        # names no product directory - a namespace covered by it alone must not appear.
        _write_repo(tmp_path)
        assert "propertyDefinitions" not in Ratchet(tmp_path).namespaces()


class TestEveryBranch:
    # Grandfathering the first route would leave the other branch unguarded.
    def test_a_method_on_two_generated_routes_gets_a_line_each(self, tmp_path: Path) -> None:
        api_ts = API_TS_FIXTURE.replace(
            "    public hogFlows(): ApiRequest {",
            "    public signalReportsActivity(id?: string, teamId?: TeamType['id']): ApiRequest {\n"
            "        return id\n"
            "            ? this.signalReports(teamId).addPathComponent(id).addPathComponent('activity')\n"
            "            : this.signalReports(teamId).addPathComponent('activity')\n"
            "    }\n\n"
            "    public hogFlows(): ApiRequest {",
        )
        generated = GENERATED_SIGNALS + (
            "export const signalsReportsActivityList = (projectId: string) => {\n"
            "    return apiMutator({ url: `/api/projects/${projectId}/signals/reports/activity/`, method: 'GET' })\n"
            "}\n"
            "export const signalsReportsActivityRetrieve = (projectId: string, id: string) => {\n"
            "    return apiMutator({ url: `/api/projects/${projectId}/signals/reports/${id}/activity/`, method: 'GET' })\n"
            "}\n"
        )
        _write_repo(tmp_path, api_ts=api_ts, generated_signals=generated)
        entries = {entry.entry for entry in Ratchet(tmp_path).redundant if entry.name == "signalReportsActivity"}
        assert entries == {
            "signalReportsActivity projects/{}/signals/reports/activity",
            "signalReportsActivity projects/{}/signals/reports/{}/activity",
        }


class TestBaselineIdentity:
    # Keyed on the name alone, a method that keeps its name and moves to another
    # generated route would stay grandfathered.
    def test_a_method_on_another_route_is_new_debt(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_repo(
            tmp_path,
            baseline=_baseline_lines("hogFlows", "propertyDefinitions", "organizationMembers", "signalReport")
            + "signalReports projects/{}/signals/old_reports\n",
        )
        monkeypatch.setattr(api_ratchet, "REPO_ROOT", tmp_path)
        result = runner.invoke(cmd_lint_api_ratchet, [])
        assert result.exit_code == 1
        assert "signalReports" in result.output

    # A short template is not automatically plumbing: the generated clients really do
    # emit routes such as /api/reminders/.
    def test_only_the_scoping_prefixes_are_exempt(self, tmp_path: Path) -> None:
        api_ts = API_TS_FIXTURE.replace(
            "    public projects(): ApiRequest {",
            "    public reminders(): ApiRequest {\n"
            "        return this.addPathComponent('reminders')\n"
            "    }\n\n"
            "    public projects(): ApiRequest {",
        )
        _write_repo(tmp_path, api_ts=api_ts)
        names = {entry.name for entry in Ratchet(tmp_path).redundant}
        assert "reminders" in names
        assert "projects" not in names
        assert "organizations" not in names


class TestBaselineFixModes:
    # Guards the fix path: --update-baseline here would grandfather the new duplicate.
    def test_prune_drops_stale_entries_and_leaves_new_debt_failing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo(tmp_path, baseline=_baseline_lines("hogFlows") + "longGoneMethod gone/route\n")
        monkeypatch.setattr(api_ratchet, "REPO_ROOT", tmp_path)
        assert runner.invoke(cmd_lint_api_ratchet, ["--prune-baseline"]).exit_code == 0
        assert read_baseline(tmp_path) == {"hogFlows projects/{}/hog_flows"}
        assert runner.invoke(cmd_lint_api_ratchet, []).exit_code == 1

    def test_update_warns_when_it_grows_the_baseline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_repo(tmp_path, baseline=_baseline_lines("hogFlows"))
        monkeypatch.setattr(api_ratchet, "REPO_ROOT", tmp_path)
        result = runner.invoke(cmd_lint_api_ratchet, ["--update-baseline"])
        assert result.exit_code == 0
        assert "grew the baseline" in result.output
        assert runner.invoke(cmd_lint_api_ratchet, []).exit_code == 0


class TestNamespaceMembers:
    # alerts() branches on an optional id, so api.alerts.list() must get the collection
    # route and not the detail one, or the report names the wrong generated function.
    def test_a_member_gets_the_route_its_arguments_select(self, tmp_path: Path) -> None:
        api_ts = API_TS_FIXTURE.replace(
            "const api = {",
            "const api = {\n"
            "    alerts: {\n"
            "        async list(): Promise<any> {\n"
            "            return await new ApiRequest().alerts().get()\n"
            "        },\n"
            "        async get(alertId: string): Promise<any> {\n"
            "            return await new ApiRequest().alerts(alertId).get()\n"
            "        },\n"
            "    },",
        ).replace(
            "    public hogFlows(): ApiRequest {",
            "    public alerts(alertId?: string, teamId?: TeamType['id']): ApiRequest {\n"
            "        if (alertId) {\n"
            "            return this.projectsDetail(teamId).addPathComponent('alerts').addPathComponent(alertId)\n"
            "        }\n"
            "        return this.projectsDetail(teamId).addPathComponent('alerts')\n"
            "    }\n\n"
            "    public hogFlows(): ApiRequest {",
        )
        _write_repo(tmp_path, api_ts=api_ts)
        members = Ratchet(tmp_path).namespace_members()
        assert members["alerts.list"].template == ("projects", "{}", "alerts")
        assert members["alerts.get"].template == ("projects", "{}", "alerts", "{}")


class TestMemberTransports:
    # A member that sends through a wrapper used to be dropped, which hid the call from
    # the report while the semgrep rule still flagged it.
    def test_a_wrapper_counts_as_its_verb_and_an_unknown_one_is_reported(self, tmp_path: Path) -> None:
        api_ts = API_TS_FIXTURE.replace(
            "    signalReports: {",
            "    signalReports: {\n"
            "        async paginated(): Promise<any> {\n"
            "            const url = new ApiRequest().signalReports().assembleFullUrl()\n"
            "            return await api.loadPaginatedResults(url)\n"
            "        },\n"
            "        async streamed(): Promise<any> {\n"
            "            return await api.stream(new ApiRequest().signalReports().assembleFullUrl(), {})\n"
            "        },",
        )
        _write_repo(tmp_path, api_ts=api_ts)
        members = Ratchet(tmp_path).namespace_members()
        assert members["signalReports.paginated"].method == "GET"
        # api.stream takes its method as a per-call option, so it stays unrecognized.
        assert members["signalReports.streamed"].method == ""
        assert members["signalReports.streamed"].transport == "stream"


class TestSemgrepRules:
    def test_rules_are_scoped_to_the_owning_product(self, tmp_path: Path) -> None:
        _write_repo(tmp_path)
        parsed = yaml.safe_load((tmp_path / api_ratchet.SEMGREP_RULE).read_text())
        by_id = {rule["id"]: rule for rule in parsed["rules"]}
        assert sorted(by_id) == [
            "prefer-codegen-api-namespaced-signals",
            "prefer-codegen-api-namespaced-workflows",
        ]
        signals = by_id["prefer-codegen-api-namespaced-signals"]
        assert signals["paths"]["include"] == ["/products/signals/frontend/", "/frontend/src/"]
        assert "/frontend/src/lib/api.ts" in signals["paths"]["exclude"]
        assert signals["severity"] == "WARNING"
        # Both nesting depths, so api.signalScout.runs.list() cannot slip through.
        assert signals["pattern-either"] == [
            {"pattern": "api.signalReports.$METHOD(...)"},
            {"pattern": "api.signalReports.$MEMBER.$METHOD(...)"},
        ]
        # A namespace only the core client covers belongs to no product, so no rule.
        assert "prefer-codegen-api-namespaced-core" not in by_id

    # Covering a shared namespace in each owner's own rule would report one call per owner.
    def test_a_namespace_two_products_own_gets_one_shared_rule_instead(self, tmp_path: Path) -> None:
        api_ts = API_TS_FIXTURE.replace(
            "    public hogFlows(): ApiRequest {",
            "    public activity(teamId?: TeamType['id']): ApiRequest {\n"
            "        return this.environmentsDetail(teamId).addPathComponent('activity')\n"
            "    }\n\n"
            "    public hogFlows(): ApiRequest {",
        ).replace(
            "const api = {",
            "const api = {\n"
            "    activity: {\n"
            "        async list(): Promise<any> {\n"
            "            return await new ApiRequest().activity().get()\n"
            "        },\n"
            "    },",
        )
        generated_signals = GENERATED_SIGNALS + (
            "export const signalsActivityList = (projectId: string) => {\n"
            "    return apiMutator({ url: `/api/projects/${projectId}/activity/`, method: 'GET' })\n"
            "}\n"
        )
        generated_workflows = GENERATED_WORKFLOWS + (
            "export const workflowsActivityList = (projectId: string) => {\n"
            "    return apiMutator({ url: `/api/projects/${projectId}/activity/`, method: 'GET' })\n"
            "}\n"
        )
        _write_repo(
            tmp_path, api_ts=api_ts, generated_signals=generated_signals, generated_workflows=generated_workflows
        )
        parsed = yaml.safe_load((tmp_path / api_ratchet.SEMGREP_RULE).read_text())
        by_id = {rule["id"]: rule for rule in parsed["rules"]}

        assert sorted(by_id) == [
            "prefer-codegen-api-namespaced-shared-activity",
            "prefer-codegen-api-namespaced-signals",
            "prefer-codegen-api-namespaced-workflows",
        ]

        signals_patterns = {
            pattern["pattern"] for pattern in by_id["prefer-codegen-api-namespaced-signals"]["pattern-either"]
        }
        workflows_patterns = {
            pattern["pattern"] for pattern in by_id["prefer-codegen-api-namespaced-workflows"]["pattern-either"]
        }
        assert signals_patterns == {"api.signalReports.$METHOD(...)", "api.signalReports.$MEMBER.$METHOD(...)"}
        assert workflows_patterns == {"api.hogFlows.$METHOD(...)", "api.hogFlows.$MEMBER.$METHOD(...)"}

        shared = by_id["prefer-codegen-api-namespaced-shared-activity"]
        assert shared["pattern-either"] == [
            {"pattern": "api.activity.$METHOD(...)"},
            {"pattern": "api.activity.$MEMBER.$METHOD(...)"},
        ]
        assert shared["paths"]["include"] == [
            "/products/signals/frontend/",
            "/products/workflows/frontend/",
            "/frontend/src/",
        ]
        assert "/frontend/src/lib/api.ts" in shared["paths"]["exclude"]
        assert shared["severity"] == "WARNING"

    def test_the_check_fails_when_the_committed_rules_are_stale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo(
            tmp_path,
            baseline=_baseline_lines(
                "hogFlows", "propertyDefinitions", "organizationMembers", "signalReport", "signalReports"
            ),
        )
        rule = tmp_path / api_ratchet.SEMGREP_RULE
        rule.write_text(rule.read_text().replace("api.signalReports.$METHOD(...)", "api.somethingElse.$METHOD(...)"))
        monkeypatch.setattr(api_ratchet, "REPO_ROOT", tmp_path)
        result = runner.invoke(cmd_lint_api_ratchet, [])
        assert result.exit_code == 1
        assert "--write-semgrep" in result.output


class TestCommand:
    def _run(self, monkeypatch: pytest.MonkeyPatch, root: Path, *args: str) -> Result:
        monkeypatch.setattr(api_ratchet, "REPO_ROOT", root)
        return runner.invoke(cmd_lint_api_ratchet, list(args))

    def test_fails_on_a_method_missing_from_the_baseline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_repo(tmp_path, baseline=_baseline_lines("signalReport", "signalReports"))
        result = self._run(monkeypatch, tmp_path)
        assert result.exit_code == 1
        assert "hogFlows" in result.output

    def test_passes_when_every_redundant_method_is_grandfathered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo(
            tmp_path,
            baseline=_baseline_lines(
                "hogFlows", "propertyDefinitions", "organizationMembers", "signalReport", "signalReports"
            ),
        )
        assert self._run(monkeypatch, tmp_path).exit_code == 0

    def test_reports_a_stale_entry_without_failing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_repo(
            tmp_path,
            baseline=_baseline_lines(
                "hogFlows", "propertyDefinitions", "organizationMembers", "signalReport", "signalReports"
            )
            + "longGoneMethod gone/route\n",
        )
        result = self._run(monkeypatch, tmp_path)
        assert result.exit_code == 0
        assert "longGoneMethod" in result.output

    def test_update_baseline_drops_stale_and_adds_new(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_repo(tmp_path, baseline="longGoneMethod gone/route\n")
        assert self._run(monkeypatch, tmp_path, "--update-baseline").exit_code == 0
        assert read_baseline(tmp_path) == {
            "signalReports projects/{}/signals/reports",
            "signalReport projects/{}/signals/reports/{}",
            "hogFlows projects/{}/hog_flows",
            "propertyDefinitions projects/{}/property_definitions",
            "organizationMembers organizations/{}/members",
        }


class TestExposedBuilders:
    def _run(self, monkeypatch: pytest.MonkeyPatch, root: Path, base_source: str | None) -> Result:
        monkeypatch.setattr(api_ratchet, "REPO_ROOT", root)
        if base_source is None:
            monkeypatch.delenv(api_ratchet.API_RATCHET_BASE_ENV, raising=False)
        else:
            monkeypatch.setenv(api_ratchet.API_RATCHET_BASE_ENV, "HEAD^1")
            monkeypatch.setattr(api_ratchet, "_read_base_api_ts", lambda repo_root, ref: base_source)
        return runner.invoke(cmd_lint_api_ratchet, [])

    def test_a_builder_the_base_already_had_fails_with_the_command_that_records_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo(
            tmp_path,
            baseline=_baseline_lines("signalReport", "signalReports", "propertyDefinitions", "organizationMembers"),
        )

        result = self._run(monkeypatch, tmp_path, API_TS_FIXTURE)

        assert result.exit_code == 1
        assert "hogFlows" in result.output
        assert "already existed" in result.output
        assert "--update-baseline --write-semgrep" in result.output
        assert "duplicate a generated client" not in result.output
        # The named command is the whole fix.
        assert runner.invoke(cmd_lint_api_ratchet, ["--update-baseline", "--write-semgrep"]).exit_code == 0
        assert self._run(monkeypatch, tmp_path, API_TS_FIXTURE).exit_code == 0

    def test_a_builder_missing_from_the_base_is_still_new_debt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo(
            tmp_path,
            baseline=_baseline_lines("signalReport", "signalReports", "propertyDefinitions", "organizationMembers"),
        )
        result = self._run(monkeypatch, tmp_path, API_TS_FIXTURE_WITHOUT_HOGFLOWS)
        assert result.exit_code == 1
        assert "duplicate a generated client" in result.output
        assert "already existed" not in result.output

    def test_without_the_env_var_the_check_stays_strict(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_repo(
            tmp_path,
            baseline=_baseline_lines("signalReport", "signalReports", "propertyDefinitions", "organizationMembers"),
        )
        result = self._run(monkeypatch, tmp_path, None)
        assert result.exit_code == 1
        assert "duplicate a generated client" in result.output
        assert "already existed" not in result.output

    def test_an_unreadable_base_ref_falls_back_to_strict_with_a_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo(
            tmp_path,
            baseline=_baseline_lines("signalReport", "signalReports", "propertyDefinitions", "organizationMembers"),
        )
        monkeypatch.setattr(api_ratchet, "REPO_ROOT", tmp_path)
        monkeypatch.setenv(api_ratchet.API_RATCHET_BASE_ENV, "HEAD^1")
        monkeypatch.setattr(api_ratchet, "_read_base_api_ts", lambda repo_root, ref: None)
        result = runner.invoke(cmd_lint_api_ratchet, [])
        assert result.exit_code == 1
        assert "could not be read" in result.output
        assert "hogFlows" in result.output
        # The warning must not corrupt the machine-readable report.
        report = json.loads(CliRunner(mix_stderr=False).invoke(cmd_lint_api_ratchet, ["--json"]).stdout)
        assert report["exposed"] == []
