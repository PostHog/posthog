import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SetupTab } from 'scenes/marketing-analytics/Setup/SetupTab'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ConversionGoalRecommendations } from './ConversionGoalRecommendations'

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
})
