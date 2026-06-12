import { connect, kea, path, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'

import { sceneLogic } from '~/scenes/sceneLogic'

import type { engineeringAnalyticsSceneLogicType } from './engineeringAnalyticsSceneLogicType'

export type EngineeringAnalyticsTab = 'pull-requests' | 'workflows' | 'quarantine'

export const TAB_DESCRIPTIONS: Record<EngineeringAnalyticsTab, string> = {
    'pull-requests': 'Pull requests and their CI status across connected repos.',
    workflows: 'Run volume, success rate, and duration per workflow over the selected window.',
    quarantine: 'Quarantined flaky tests: what is masked, who owns it, and when it expires.',
}

const SCENE_KEY_TO_TAB: Record<string, EngineeringAnalyticsTab> = {
    engineeringAnalytics: 'pull-requests',
    engineeringAnalyticsWorkflows: 'workflows',
    engineeringAnalyticsQuarantine: 'quarantine',
}

export const engineeringAnalyticsSceneLogic = kea<engineeringAnalyticsSceneLogicType>([
    path(['products', 'engineering_analytics', 'frontend', 'scenes', 'engineeringAnalyticsSceneLogic']),
    tabAwareScene(),
    connect(() => ({
        values: [sceneLogic, ['sceneKey']],
    })),
    selectors({
        activeTab: [
            (s) => [s.sceneKey],
            (sceneKey: string): EngineeringAnalyticsTab => SCENE_KEY_TO_TAB[sceneKey] ?? 'pull-requests',
        ],
    }),
])
