from __future__ import annotations

from pathlib import Path

import pytest

from hogli_commands import api_ratchet
from hogli_commands.product.ts_helpers import codegen_call_sites, count_manual_api_calls

API_TS = """\
export class ApiRequest {
    public projectsDetail(id: ProjectType['id'] = ApiConfig.getCurrentProjectId()): ApiRequest {
        return this.addPathComponent('projects').addPathComponent(id)
    }

    public signalReports(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('signals').addPathComponent('reports')
    }

    public signalReport(id: string, teamId?: TeamType['id']): ApiRequest {
        return this.signalReports(teamId).addPathComponent(id)
    }

    public signalRules(ruleType: string, teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('signals').addPathComponent(ruleType)
    }

    public signalRule(ruleType: string, id: string): ApiRequest {
        return this.signalRules(ruleType).addPathComponent(id)
    }

    public signalReorderRules(ruleType: string): ApiRequest {
        return this.signalRules(ruleType).addPathComponent('reorder')
    }

    public signalScoutRuns(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('signals').addPathComponent('scout').addPathComponent('runs')
    }

    public comments(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('comments')
    }
}

const api = {
    signalReports: {
        async list(): Promise<any> {
            return await new ApiRequest().signalReports().get()
        },
        async setState(id: string, data: any): Promise<any> {
            return await new ApiRequest().signalReport(id).withAction('state').create({ data })
        },
        async createRule(ruleType: string, data: any): Promise<any> {
            return await new ApiRequest().signalRules(ruleType).create({ data })
        },
        async updateRule(ruleType: string, id: string, data: any): Promise<any> {
            return await new ApiRequest().signalRule(ruleType, id).update({ data })
        },
        async reorderRules(ruleType: string, orders: any): Promise<any> {
            return await new ApiRequest().signalReorderRules(ruleType).update({ data: { orders } })
        },
        async availableReviewers(): Promise<any> {
            return await new ApiRequest().signalReports().withAction('available_reviewers').get()
        },
    },
    signalScout: {
        runs: {
            async list(): Promise<any> {
                return await new ApiRequest().signalScoutRuns().get()
            },
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
export const getSignalsReportsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/reports/`
}
export const signalsReportsList = async (projectId: string) => {
    return apiMutator({ url: getSignalsReportsListUrl(projectId), method: 'GET' })
}
export const signalsReportsStateCreate = async (projectId: string, id: string) => {
    return apiMutator({ url: getSignalsReportsStateCreateUrl(projectId, id), method: 'POST' })
}
export const getSignalsReportsStateCreateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/reports/${id}/state/`
}
export const signalsAssignmentRulesCreate = async (projectId: string) => {
    return apiMutator({ url: getSignalsAssignmentRulesCreateUrl(projectId), method: 'POST' })
}
export const getSignalsAssignmentRulesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/assignment_rules/`
}
export const signalsGroupingRulesCreate = async (projectId: string) => {
    return apiMutator({ url: getSignalsGroupingRulesCreateUrl(projectId), method: 'POST' })
}
export const getSignalsGroupingRulesCreateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/grouping_rules/`
}
export const signalsAssignmentRulesPartialUpdate = async (projectId: string, id: string) => {
    return apiMutator({ url: getSignalsAssignmentRulesPartialUpdateUrl(projectId, id), method: 'PATCH' })
}
export const getSignalsAssignmentRulesPartialUpdateUrl = (projectId: string, id: string) => {
    return `/api/projects/${projectId}/signals/assignment_rules/${id}/`
}
export const signalsAssignmentRulesReorderPartialUpdate = async (projectId: string) => {
    return apiMutator({ url: getSignalsAssignmentRulesReorderPartialUpdateUrl(projectId), method: 'PATCH' })
}
export const getSignalsAssignmentRulesReorderPartialUpdateUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/assignment_rules/reorder/`
}
export const getSignalsScoutRunsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/signals/scout/runs/`
}
export const signalsScoutRunsList = async (projectId: string) => {
    return apiMutator({ url: getSignalsScoutRunsListUrl(projectId), method: 'GET' })
}
"""

GENERATED_COMMENTS = """\
export const getCommentsListUrl = (projectId: string) => {
    return `/api/projects/${projectId}/comments/`
}
export const commentsList = async (projectId: string) => {
    return apiMutator({ url: getCommentsListUrl(projectId), method: 'GET' })
}
"""

PRODUCT_FILE = """\
import api from 'lib/api'

export const load = async (): Promise<void> => {
    await api.signalReports.list()
    await api.signalReports.setState(id, { state: 'resolved' })
    await api.signalScout.runs.list({ limit: 10 })
    await api.signalReports.availableReviewers()
    await api.signalReports
        .setState(id, { state: 'resolved' })
    await api.signalReports.createRule(SignalRuleType.Grouping, values.rule.id)
    await api.signalReports.createRule(ruleTypeFromProps, rule)
    await api.signalReports.updateRule(SignalRuleType.Assignment, id, rule)
    await api.comments.list()
    await api.get(`api/projects/${projectId}/signals/config/`)
}
"""


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "frontend/src/lib").mkdir(parents=True)
    (tmp_path / "frontend/src/lib/api.ts").write_text(API_TS)
    for product, generated in (("signals", GENERATED_SIGNALS), ("platform_features", GENERATED_COMMENTS)):
        directory = tmp_path / "products" / product / "frontend" / "generated"
        directory.mkdir(parents=True)
        (directory / "api.ts").write_text(generated)
    (tmp_path / "products/signals/frontend/reportsLogic.ts").write_text(PRODUCT_FILE)
    monkeypatch.setattr(api_ratchet, "REPO_ROOT", tmp_path)
    api_ratchet._ratchet.cache_clear()
    return tmp_path


class TestParameterisedRoutes:
    # The route is a mask, so the call's own argument decides which generated function
    # replaces it; reporting the mask as unmatched sent the reader looking for nothing.
    def test_a_literal_argument_picks_the_generated_function(self, repo: Path) -> None:
        sites = codegen_call_sites(repo / "products/signals/frontend")
        by_line = {site.line: site for site in sites if site.verb == "signalReports.createRule"}
        picked = [site.generated_equivalent for site in by_line.values()]
        assert "signalsGroupingRulesCreate" in picked
        # A value the call site does not spell out leaves every candidate on the line.
        ambiguous = next(name for name in picked if name is not None and " | " in name)
        assert "signalsAssignmentRulesCreate" in ambiguous
        assert "signalsGroupingRulesCreate" in ambiguous

    # `values.rule.id` is not the selector - it's a plain object access - but its
    # dotted tokens ("rule", "id") match every candidate's shared "Rules" suffix and
    # used to turn a spelled-out literal selector ambiguous.
    def test_a_later_dotted_argument_does_not_dilute_the_selector(self, repo: Path) -> None:
        sites = codegen_call_sites(repo / "products/signals/frontend")
        picked = [site.generated_equivalent for site in sites if site.verb == "signalReports.createRule"]
        assert picked.count("signalsGroupingRulesCreate") == 1

    # An id hole and a rule-type hole both read as `{p}` in the mask. A static action
    # route sharing the id's position (`.../reorder/`) is a different operation, not
    # this one with an id, so it must not survive as a second candidate.
    def test_a_static_action_route_does_not_match_the_id_hole(self, repo: Path) -> None:
        sites = codegen_call_sites(repo / "products/signals/frontend")
        update = next(site for site in sites if site.verb == "signalReports.updateRule")
        assert update.generated_equivalent == "signalsAssignmentRulesPartialUpdate"


class TestManualApiCalls:
    # Guards the blind spot: an owned namespace used to score as zero manual calls.
    def test_counts_owned_namespaces_and_skips_foreign_ones(self, repo: Path) -> None:
        # seven api.signalReports calls, one of them broken across lines, one nested
        # api.signalScout.runs.list, one api.get; api.comments belongs to platform_features
        assert count_manual_api_calls(repo / "products/signals/frontend") == 9

    def test_call_sites_mark_a_namespaced_call_as_covered(self, repo: Path) -> None:
        sites = codegen_call_sites(repo / "products/signals/frontend")
        assert sorted(site.verb for site in sites) == [
            "get",
            "signalReports.availableReviewers",
            "signalReports.createRule",
            "signalReports.createRule",
            "signalReports.list",
            "signalReports.setState",
            "signalReports.setState",
            "signalReports.updateRule",
            # A nested chain counts once, with its full member path.
            "signalScout.runs.list",
        ]
        covered = next(site for site in sites if site.verb == "signalReports.list")
        assert covered.namespaced
        assert covered.generated_equivalent == "signalsReportsList"
        # The client has no operation for this member, so it is a gap, not a twin.
        gap = next(site for site in sites if site.verb == "signalReports.availableReviewers")
        assert not gap.namespaced
        assert gap.generated_equivalent is None
