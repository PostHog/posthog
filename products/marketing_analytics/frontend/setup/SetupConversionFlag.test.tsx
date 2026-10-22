import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SetupTab } from 'scenes/marketing-analytics/Setup/SetupTab'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ConversionGoalRecommendations } from './ConversionGoalRecommendations'
import { DashboardConversionRecommendations } from './DashboardConversionRecommendations'
import { DashboardSetupPrompt } from './DashboardSetupPrompt'
import { dashboardSetupPromptsLogic } from './dashboardSetupPromptsLogic'

jest.mock('./ConversionGoalRecommendations', () => ({
    ConversionGoalRecommendations: jest.fn(() => <button>Review recommendations</button>),
}))
jest.mock('scenes/marketing-analytics/Setup/setupSections', () => ({
    SETUP_SECTIONS: [
        {
            key: 'conversion-goals',
            label: 'Conversion goals',
            content: <button>Add conversion goal</button>,
        },
    ],
}))
jest.mock('scenes/marketing-analytics/Setup/SectionSuggestions', () => ({ SectionSuggestions: () => null }))
jest.mock('scenes/marketing-analytics/Setup/SuggestionModal', () => ({ SuggestionModal: () => null }))
jest.mock(
    'scenes/web-analytics/tabs/marketing-analytics/frontend/components/settings/IntegrationSettingsModal',
    () => ({ IntegrationSettingsModal: () => null })
)

describe('conversion setup feature flag', () => {
    beforeEach(() => {
        localStorage.clear()
        useMocks({ get: { '/api/environments/:team_id/marketing_analytics/setup_plan/': { suggestions: [] } } })
        initKeaTests()
        jest.clearAllMocks()
    })
    afterEach(cleanup)

    it('keeps manual setup mounted and only mounts AI recommendations while their flag is enabled', () => {
        render(<SetupTab />)
        expect(screen.getByText('Add conversion goal')).toBeVisible()
        expect(ConversionGoalRecommendations).not.toHaveBeenCalled()

        act(() =>
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI], {
                [FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI]: true,
            })
        )
        expect(screen.getByText('Review recommendations')).toBeVisible()
        expect(screen.getByText('Add conversion goal')).toBeVisible()

        act(() =>
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI]: false,
            })
        )
        expect(screen.queryByText('Review recommendations')).not.toBeInTheDocument()
        expect(screen.getByText('Add conversion goal')).toBeVisible()
    })

    it.each([
        [false, false, false, false],
        [false, false, true, false],
        [true, false, false, false],
        [true, false, true, true],
        [false, true, false, false],
        [false, true, true, true],
    ])('gates dashboard recommendations with setup=%s, new dashboard=%s, AI=%s', (setup, dashboard, ai, visible) => {
        featureFlagLogic.actions.setFeatureFlags([], {
            [FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP]: setup,
            [FEATURE_FLAGS.MARKETING_ANALYTICS_NEW_DASHBOARD]: dashboard,
            [FEATURE_FLAGS.MARKETING_ANALYTICS_CONVERSION_SETUP_AI]: ai,
            [FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]: true,
        })
        render(<DashboardConversionRecommendations />)
        expect(!!screen.queryByText('Review recommendations')).toBe(visible)
        expect(!!jest.mocked(ConversionGoalRecommendations).mock.calls.length).toBe(visible)
    })

    it('keeps dismissed sources accessible without Setup and restores them from Setup', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP]: true })
        render(
            <DashboardSetupPrompt kind="sources">
                {(dismissButton) => <div>Source suggestions{dismissButton}</div>}
            </DashboardSetupPrompt>
        )
        fireEvent.click(screen.getByLabelText('Dismiss source suggestions'))
        expect(screen.queryByText('Source suggestions')).not.toBeInTheDocument()
        act(() => featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP]: false }))
        expect(screen.getByText('Source suggestions')).toBeVisible()
        expect(screen.queryByLabelText('Dismiss source suggestions')).not.toBeInTheDocument()
        act(() => featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP]: true }))
        expect(screen.queryByText('Source suggestions')).not.toBeInTheDocument()
        act(() =>
            dashboardSetupPromptsLogic({
                projectId: teamLogic.values.currentTeamId!,
                userId: userLogic.values.user?.uuid,
            }).actions.restore('sources')
        )
        expect(screen.getByText('Source suggestions')).toBeVisible()
    })

    it('keeps an error and its retry visible after the source suggestions were dismissed', () => {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.MARKETING_ANALYTICS_SETUP]: true })
        const { rerender } = render(
            <DashboardSetupPrompt kind="sources">
                {(dismissButton) => <div>Source suggestions{dismissButton}</div>}
            </DashboardSetupPrompt>
        )
        fireEvent.click(screen.getByLabelText('Dismiss source suggestions'))
        rerender(
            <DashboardSetupPrompt kind="sources" dismissible={false}>
                {(dismissButton) => (
                    <div>
                        <button>Retry source scan</button>
                        {dismissButton}
                    </div>
                )}
            </DashboardSetupPrompt>
        )
        expect(screen.getByText('Retry source scan')).toBeVisible()
        expect(screen.queryByLabelText('Dismiss source suggestions')).not.toBeInTheDocument()
    })
})
