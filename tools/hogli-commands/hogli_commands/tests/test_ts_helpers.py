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

    public comments(teamId?: TeamType['id']): ApiRequest {
        return this.projectsDetail(teamId).addPathComponent('comments')
    }
}

const api = {
    signalReports: {
        async list(): Promise<any> {
            return await new ApiRequest().signalReports().get()
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


class TestManualApiCalls:
    # Guards the blind spot: an owned namespace used to score as zero manual calls.
    def test_counts_owned_namespaces_and_skips_foreign_ones(self, repo: Path) -> None:
        # two api.signalReports calls and one api.get; api.comments belongs to platform_features
        assert count_manual_api_calls(repo / "products/signals/frontend") == 3

    def test_call_sites_mark_a_namespaced_call_as_covered(self, repo: Path) -> None:
        sites = codegen_call_sites(repo / "products/signals/frontend")
        assert sorted(site.verb for site in sites) == [
            "get",
            "signalReports.list",
            "signalReports.setState",
        ]
        namespaced = next(site for site in sites if site.verb == "signalReports.list")
        assert namespaced.namespaced
        assert namespaced.generated_equivalent is None
