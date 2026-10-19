import { MOCK_DEFAULT_TEAM, MOCK_DEFAULT_USER } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { maxMocks } from 'scenes/max/testUtils'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'
import {
    MarketingAnalyticsTab,
    SetupSection,
    marketingAnalyticsLogic,
} from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ConversionGoalPreviewApi } from '../generated/api.schemas'
import { conversionGoalDraftLogic } from './conversionGoalDraftLogic'
import { ConversionGoalRecommendations } from './ConversionGoalRecommendations'
import { ConversionGoalRecommendationsBanner } from './ConversionGoalRecommendationsBanner'
import { ConversionGoalSetupIntegration } from './ConversionGoalSetupIntegration'

const draft: ConversionGoalPreviewApi = {
    goal: {
        kind: 'EventsNode',
        event: 'trial_started',
        conversion_goal_id: '__preview__',
        conversion_goal_name: 'Trial started',
        schema_map: {},
        math: 'total',
    },
    date_from: '-14d',
    date_to: 'now',
}

describe('conversion goal dashboard notice', () => {
    beforeEach(() => {
        localStorage.clear()
        useMocks({
            ...maxMocks,
            get: {
                ...maxMocks.get,
                '/api/environments/:team_id/marketing_analytics/conversion_recommendations/': {
                    latest_run: null,
                    result_run: null,
                    results: { recommendations: [], limitations: [] },
                    can_generate: false,
                },
                '/api/environments/:team_id/marketing_analytics/setup_plan/': { suggestions: [] },
            },
        })
        initKeaTests()
        const flags = [
            FEATURE_FLAGS.PHAI_SANDBOX_MODE,
            FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN,
            FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI,
        ]
        featureFlagLogic.actions.setFeatureFlags(flags, Object.fromEntries(flags.map((flag) => [flag, true])))
    })
    afterEach(cleanup)

    it('keeps a dismissed notice hidden after completion and remount while the draft remains reviewable in setup', () => {
        const { rerender } = render(
            <>
                <ConversionGoalSetupIntegration />
                <ConversionGoalRecommendationsBanner />
            </>
        )
        const logic = conversionGoalDraftLogic({ projectId: MOCK_DEFAULT_TEAM.id })
        act(() => logic.actions.setBusy('preview'))
        fireEvent.click(screen.getByLabelText('close'))
        act(() => {
            logic.actions.setBusy(null)
            logic.actions.receiveDraft(draft)
        })
        expect(screen.queryByText('A conversion goal draft is ready to review')).not.toBeInTheDocument()

        rerender(
            <>
                <ConversionGoalSetupIntegration />
                <ConversionGoalRecommendations />
            </>
        )
        expect(screen.getAllByText('Review draft')[0]).toBeVisible()
        expect(logic.values.pendingDraft).toEqual(draft)

        rerender(
            <>
                <ConversionGoalSetupIntegration />
                <ConversionGoalRecommendationsBanner />
            </>
        )
        expect(screen.queryByLabelText('close')).not.toBeInTheDocument()
        expect(logic.values.pendingDraft).toEqual(draft)
    })

    it('scopes dismissal to the user and project and links other notices to conversion setup', () => {
        render(<ConversionGoalRecommendationsBanner />)
        fireEvent.click(screen.getByLabelText('close'))
        act(() => teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 998 }))
        expect(screen.getAllByText('Review in setup')[0]).toBeVisible()
        fireEvent.click(screen.getAllByText('Review in setup')[0])
        expect(marketingAnalyticsLogic.values.activeTab).toBe(MarketingAnalyticsTab.SETUP)
        expect(marketingAnalyticsLogic.values.setupSection).toBe(SetupSection.CONVERSION_GOALS)

        act(() => teamLogic.actions.loadCurrentTeamSuccess(MOCK_DEFAULT_TEAM))
        expect(screen.queryByLabelText('close')).not.toBeInTheDocument()
        act(() => userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, uuid: 'another-example-user' }))
        expect(screen.getAllByText('Review in setup')[0]).toBeVisible()
        act(() => featureFlagLogic.actions.setFeatureFlags([], {}))
        expect(screen.queryAllByText('Review in setup')).toHaveLength(0)
    })
})
