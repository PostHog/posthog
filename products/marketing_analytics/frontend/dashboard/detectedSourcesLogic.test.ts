import { MOCK_TEAM_ID } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { setupPlanLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { detectedSourcesLogic } from './detectedSourcesLogic'

describe('detectedSourcesLogic', () => {
    let setupPlanRequests: number

    beforeEach(() => {
        setupPlanRequests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/marketing_analytics/setup_plan': () => {
                    setupPlanRequests += 1
                    return [200, { suggestions: [], readiness: [], degraded: [], truncated: false, summary: '' }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([], {})
        setupPlanLogic.mount()
    })

    it('starts the scan when the onboarding flag arrives after mount', async () => {
        const logic = detectedSourcesLogic({ teamId: MOCK_TEAM_ID })
        logic.mount()
        expect(setupPlanLogic.values.setupPlanLoading).toBe(false)

        await expectLogic(setupPlanLogic, () => {
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]: true,
            })
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]: true,
            })
        }).toDispatchActions(['loadSetupPlan', 'loadSetupPlanSuccess'])
        expect(setupPlanRequests).toBe(1)
        logic.unmount()
    })
    it('restores dashboard dismissals through the shared Setup controls', async () => {
        const logic = detectedSourcesLogic({ teamId: MOCK_TEAM_ID })
        logic.mount()
        const id = 'connect_source:GoogleAds'
        setupPlanLogic.actions.loadSetupPlanSuccess({
            suggestions: [
                {
                    id,
                    kind: 'connect_source',
                    source: 'deterministic',
                    severity: 'info',
                    confidence: 0.8,
                    title: 'Connect Google Ads',
                    evidence: 'Campaign tracking found in recent events.',
                    unlocks: ['cost'],
                    apply: { op: 'open_source_wizard', kind: 'GoogleAds' },
                    also_recommended: [],
                    safe_to_batch: false,
                    rank_score: 10,
                    integration: 'GoogleAds',
                    deep_link: null,
                    docs_url: null,
                    spend_at_risk: 0,
                    event_volume: 12,
                },
            ],
            readiness: [],
            degraded: [],
            truncated: false,
            summary: '',
            source_scanned_at: null,
        })
        logic.actions.dismissSource(id)
        expect(setupPlanLogic.values.visibleSuggestions).toHaveLength(0)
        expect(setupPlanLogic.values.dismissedSuggestions).toHaveLength(1)
        setupPlanLogic.actions.restoreSuggestion(id)
        expect(setupPlanLogic.values.visibleSuggestions).toHaveLength(1)
        logic.unmount()
    })
})
