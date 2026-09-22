from __future__ import annotations

from pathlib import Path

import pytest

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

    public query(teamId?: TeamType['id'], queryKind?: string): ApiRequest {
        const apiRequest = this.environmentsDetail(teamId).addPathComponent('query')
        if (queryKind) {
            return apiRequest.addPathComponent(queryKind)
        }
        return apiRequest
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
"""


def _write_repo(root: Path, api_ts: str = API_TS_FIXTURE, baseline: str | None = None) -> None:
    (root / "frontend/src/lib").mkdir(parents=True, exist_ok=True)
    (root / "frontend/src/lib/api.ts").write_text(api_ts)
    (root / "products/signals/frontend/generated").mkdir(parents=True, exist_ok=True)
    (root / "products/signals/frontend/generated/api.ts").write_text(GENERATED_SIGNALS)
    (root / "products/workflows/frontend/generated").mkdir(parents=True, exist_ok=True)
    (root / "products/workflows/frontend/generated/api.ts").write_text(GENERATED_WORKFLOWS)
    (root / api_ratchet.CORE_GENERATED).parent.mkdir(parents=True, exist_ok=True)
    (root / api_ratchet.CORE_GENERATED).write_text(GENERATED_CORE)
    if baseline is not None:
        (root / api_ratchet.BASELINE).write_text(baseline)


class TestApiRequestResolver:
    @parameterized.expand(
        [
            ("literal chain off projectsDetail", "signalReports", ["projects/{}/signals/reports"]),
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
            # The chain root lives in the body, not in the return statement. Resolving
            # the return alone drops environments/{} and the URL looks like /api/query.
            (
                "a chain assigned to a local keeps its root",
                "query",
                ["environments/{}/query/{}", "environments/{}/query"],
            ),
            ("the root path method resolves to its own segment", "projects", ["projects"]),
        ]
    )
    def test_resolves(self, _name: str, method: str, expected: list[str]) -> None:
        resolver = ApiRequestResolver(API_TS_FIXTURE)
        assert ["/".join(template) for template in resolver.templates(method)] == expected

    def test_verb_methods_are_not_path_methods(self) -> None:
        # `get` returns a Promise, so counting it would give every namespace a bare
        # /api/projects/{} template and match half the generated output.
        assert "get" not in ApiRequestResolver(API_TS_FIXTURE).method_names()


class TestRatchet:
    def test_flags_methods_with_a_generated_twin(self, tmp_path: Path) -> None:
        _write_repo(tmp_path)
        ratchet = Ratchet(tmp_path)
        assert {name: sorted(products) for name, (_, products) in ratchet.redundant.items()} == {
            "signalReports": ["signals"],
            "signalReport": ["signals"],
            "hogFlows": ["workflows"],
            "propertyDefinitions": ["core"],
        }

    def test_namespaces_lists_only_those_calling_a_redundant_method(self, tmp_path: Path) -> None:
        _write_repo(tmp_path)
        assert {ns: sorted(products) for ns, products in Ratchet(tmp_path).namespaces().items()} == {
            "signalReports": ["signals"],
            "hogFlows": ["workflows"],
        }


class TestBaselineFixModes:
    # Guards the fix path: --update-baseline here would grandfather the new duplicate.
    def test_prune_drops_stale_entries_and_leaves_new_debt_failing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo(tmp_path, baseline="hogFlows\nlongGoneMethod\n")
        monkeypatch.setattr(api_ratchet, "REPO_ROOT", tmp_path)
        assert runner.invoke(cmd_lint_api_ratchet, ["--prune-baseline"]).exit_code == 0
        assert read_baseline(tmp_path) == {"hogFlows"}
        assert runner.invoke(cmd_lint_api_ratchet, []).exit_code == 1

    def test_update_warns_that_it_grandfathers_new_debt(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_repo(tmp_path, baseline="hogFlows\n")
        monkeypatch.setattr(api_ratchet, "REPO_ROOT", tmp_path)
        result = runner.invoke(cmd_lint_api_ratchet, ["--update-baseline"])
        assert result.exit_code == 0
        assert "grandfathers new debt" in result.output
        assert runner.invoke(cmd_lint_api_ratchet, []).exit_code == 0


class TestCommand:
    def _run(self, monkeypatch: pytest.MonkeyPatch, root: Path, *args: str) -> Result:
        monkeypatch.setattr(api_ratchet, "REPO_ROOT", root)
        return runner.invoke(cmd_lint_api_ratchet, list(args))

    def test_fails_on_a_method_missing_from_the_baseline(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_repo(tmp_path, baseline="signalReport\nsignalReports\n")
        result = self._run(monkeypatch, tmp_path)
        assert result.exit_code == 1
        assert "hogFlows" in result.output

    def test_passes_when_every_redundant_method_is_grandfathered(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_repo(tmp_path, baseline="hogFlows\npropertyDefinitions\nsignalReport\nsignalReports\n")
        assert self._run(monkeypatch, tmp_path).exit_code == 0

    def test_reports_a_stale_entry_without_failing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_repo(tmp_path, baseline="hogFlows\npropertyDefinitions\nsignalReport\nsignalReports\nlongGoneMethod\n")
        result = self._run(monkeypatch, tmp_path)
        assert result.exit_code == 0
        assert "longGoneMethod" in result.output

    def test_update_baseline_drops_stale_and_adds_new(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _write_repo(tmp_path, baseline="longGoneMethod\n")
        assert self._run(monkeypatch, tmp_path, "--update-baseline").exit_code == 0
        assert read_baseline(tmp_path) == {"signalReports", "signalReport", "hogFlows", "propertyDefinitions"}
