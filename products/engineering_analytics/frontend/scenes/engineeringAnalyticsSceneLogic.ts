import { connect, kea, path, selectors } from 'kea'

import { sceneLogic } from '~/scenes/sceneLogic'

import type { engineeringAnalyticsSceneLogicType } from './engineeringAnalyticsSceneLogicType'

/** The root scene's views: the repo hub landing, the PR list page, the workflow list page, test health, and teams. */
export type EngineeringAnalyticsView = 'hub' | 'pull-requests' | 'workflows' | 'test-health' | 'teams'

export const VIEW_DESCRIPTIONS: Record<EngineeringAnalyticsView, string> = {
    hub: 'CI health, pull requests, workflows, and cost for the connected repo.',
    'pull-requests': 'Pull requests and their CI status across connected repos.',
    workflows: 'Run volume, success rate, and duration per workflow over the selected window.',
    'test-health': 'Flaky tests under quarantine: what is masked, who owns it, and when it expires.',
    teams: 'CI test surfaces rolled up by owning team: flaky signal and failures, with prior-window deltas.',
}

const SCENE_KEY_TO_VIEW: Record<string, EngineeringAnalyticsView> = {
    engineeringAnalytics: 'hub',
    engineeringAnalyticsPullRequestList: 'pull-requests',
    engineeringAnalyticsWorkflows: 'workflows',
    engineeringAnalyticsTestHealth: 'test-health',
    engineeringAnalyticsTeams: 'teams',
}

export const engineeringAnalyticsSceneLogic = kea<engineeringAnalyticsSceneLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'engineeringAnalyticsSceneLogic']),
    connect(() => ({
        values: [sceneLogic, ['sceneKey']],
    })),
    selectors({
        activeView: [
            (s) => [s.sceneKey],
            (sceneKey: string): EngineeringAnalyticsView => SCENE_KEY_TO_VIEW[sceneKey] ?? 'hub',
        ],
    }),
])
