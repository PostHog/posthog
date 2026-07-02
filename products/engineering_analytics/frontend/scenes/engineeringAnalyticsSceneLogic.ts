import { connect, kea, path, selectors } from 'kea'

import { sceneLogic } from '~/scenes/sceneLogic'

import type { engineeringAnalyticsSceneLogicType } from './engineeringAnalyticsSceneLogicType'

/** The root scene's views: the repo hub landing, the PR list page, and test health. */
export type EngineeringAnalyticsView = 'hub' | 'pull-requests' | 'test-health'

export const VIEW_DESCRIPTIONS: Record<EngineeringAnalyticsView, string> = {
    hub: 'CI health and cost for the connected repo — failures, pull requests, workflows, and spend in one place.',
    'pull-requests': 'Pull requests and their CI status across connected repos.',
    'test-health': 'Flaky tests under quarantine: what is masked, who owns it, and when it expires.',
}

const SCENE_KEY_TO_VIEW: Record<string, EngineeringAnalyticsView> = {
    engineeringAnalytics: 'hub',
    engineeringAnalyticsPullRequestList: 'pull-requests',
    engineeringAnalyticsTestHealth: 'test-health',
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
