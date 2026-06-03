import { connect, kea, path, selectors } from 'kea'

import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'

import { sceneLogic } from '~/scenes/sceneLogic'

import type { engineeringAnalyticsSceneLogicType } from './engineeringAnalyticsSceneLogicType'

export type EngineeringAnalyticsTab = 'pull-requests' | 'workflows'

export const TAB_DESCRIPTIONS: Record<EngineeringAnalyticsTab, string> = {
    'pull-requests': 'Open PRs are the unit of work — CI health, throughput, and where engineering hours go.',
    workflows: 'Run volume, success rate, and duration per workflow over the last 30 days.',
}

const SCENE_KEY_TO_TAB: Record<string, EngineeringAnalyticsTab> = {
    engineeringAnalytics: 'pull-requests',
    engineeringAnalyticsWorkflows: 'workflows',
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
