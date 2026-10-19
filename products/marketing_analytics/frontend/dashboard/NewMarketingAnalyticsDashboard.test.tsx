import { cleanup, render, screen } from '@testing-library/react'
import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'

import { NewMarketingAnalyticsDashboard } from './NewMarketingAnalyticsDashboard'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: jest.fn(),
    useActions: () => new Proxy({}, { get: () => jest.fn() }),
}))
jest.mock('scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic', () => ({
    marketingAnalyticsLogic: {},
    MarketingDashboardView: {
        OVERVIEW: 'overview',
        ACQUISITION: 'acquisition',
        ENGAGEMENT: 'engagement',
        RETENTION: 'retention',
        CONVERSION: 'conversion',
    },
}))
jest.mock('lib/logic/featureFlagLogic', () => ({ featureFlagLogic: {} }))
jest.mock('scenes/teamLogic', () => ({ teamLogic: {} }))
jest.mock('scenes/marketing-analytics/Onboarding/marketingOnboardingLogic', () => ({ marketingOnboardingLogic: {} }))
jest.mock('scenes/marketing-analytics/Onboarding/Onboarding', () => ({
    Onboarding: () => <div>Marketing onboarding</div>,
}))
jest.mock(
    'scenes/web-analytics/tabs/marketing-analytics/frontend/components/MarketingAnalyticsSourceStatusBanner',
    () => ({ MarketingAnalyticsSourceStatusBanner: () => null })
)
jest.mock('./marketingDashboardLogic', () => ({ marketingDashboardLogic: {} }))
jest.mock('./header/MarketingDashboardHeader', () => ({
    MarketingDashboardHeader: () => <div>Dashboard controls</div>,
}))
jest.mock('./DetectedSources', () => ({ DetectedSources: () => null }))
jest.mock('./DashboardSetupSuggestions', () => ({ DashboardSetupSuggestions: () => null }))
jest.mock('../setup/ConversionGoalRecommendationsBanner', () => ({ ConversionGoalRecommendationsBanner: () => null }))
jest.mock('./askAi/AskPostHogAi', () => ({ AskPostHogAi: () => null }))
jest.mock('./sections/OverviewSection', () => ({ OverviewSection: () => <div>Overview metrics</div> }))
jest.mock('./sections/AcquisitionSection', () => ({ AcquisitionSection: () => <div>Acquisition metrics</div> }))
jest.mock('./sections/EngagementSection', () => ({ EngagementSection: () => <div>Engagement metrics</div> }))
jest.mock('./sections/RetentionSection', () => ({ RetentionSection: () => <div>Retention metrics</div> }))
jest.mock('./sections/ConversionSection', () => ({ ConversionSection: () => <div>Conversion metrics</div> }))

describe('NewMarketingAnalyticsDashboard', () => {
    afterEach(cleanup)

    it.each(['ads', 'gsc', 'gsc-without-flag', 'none', 'onboarding-disabled', 'loading'] as const)(
        'handles source onboarding for %s',
        (sourceState) => {
            jest.mocked(useValues).mockReturnValue({
                dashboardView: 'overview',
                featureFlags: {
                    [FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS]: sourceState === 'gsc',
                    [FEATURE_FLAGS.MARKETING_ANALYTICS_SOURCE_ONBOARDING]: sourceState !== 'onboarding-disabled',
                },
                nativeSources: sourceState === 'ads' ? [{ id: 'connected-source', source_type: 'GoogleAds' }] : [],
                dataWarehouseSources: {
                    results: sourceState.startsWith('gsc') ? [{ source_type: 'GoogleSearchConsole' }] : [],
                },
                validExternalTables: [],
                showOnboarding: sourceState !== 'ads',
                loading: sourceState === 'loading',
                currentTeamLoading: false,
            })
            render(<NewMarketingAnalyticsDashboard />)
            if (sourceState === 'gsc-without-flag' || sourceState === 'none') {
                expect(screen.getByText('Marketing onboarding')).not.toBeNull()
                expect(screen.queryByText('Dashboard controls')).toBeNull()
            } else {
                expect(screen.queryByText('Marketing onboarding')).toBeNull()
                expect(screen.getByText('Dashboard controls')).not.toBeNull()
                expect(screen.getByText('Overview metrics')).not.toBeNull()
            }
        }
    )

    it('mounts only the selected section as navigation changes', () => {
        const state = {
            dashboardView: 'overview',
            featureFlags: {},
            nativeSources: [],
            validExternalTables: [],
            loading: false,
            showOnboarding: false,
        }
        jest.mocked(useValues).mockImplementation(() => state)
        const view = render(<NewMarketingAnalyticsDashboard />)
        for (const section of ['acquisition', 'engagement', 'retention', 'conversion', 'overview']) {
            state.dashboardView = section
            view.rerender(<NewMarketingAnalyticsDashboard />)
            expect(screen.getByText(`${section[0].toUpperCase()}${section.slice(1)} metrics`)).not.toBeNull()
            expect(screen.getAllByText(/metrics$/)).toHaveLength(1)
        }
    })
})
