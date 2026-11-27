import { IconLightBulb } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { RecommendationsShownState } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { RecommendationsConnectGoogleAdsButton } from './RecommendationsConnectGoogleAdsButton'

export type RecommendationsIdleState = Exclude<RecommendationsShownState, 'recommendations'>

const IDLE_MESSAGES: Record<RecommendationsIdleState, string | null> = {
    no_connected_source: 'Connect Google Ads to get recommendations on budgets, search terms and wasted spend.',
    no_selected_source:
        'Select a Google Ads or Google Search Console source with synced tables to see recommendations.',
    error: null,
    empty: 'No recommendations for this period.',
}

const EMPTY_REASON =
    'Campaign rules compare active campaigns in the same ad account, so an account with one campaign gets few. Search term rules need synced search term tables, and Google Search Console for the organic ones.'

export function recommendationsIdleCopy(state: RecommendationsIdleState): {
    message: string | null
    disabledReason: string
} {
    const message = IDLE_MESSAGES[state]
    return {
        message,
        disabledReason: state === 'empty' ? EMPTY_REASON : (message ?? 'Recommendations could not load.'),
    }
}

export function RecommendationsIdle({ state }: { state: RecommendationsIdleState }): JSX.Element {
    const { message, disabledReason } = recommendationsIdleCopy(state)

    return (
        <>
            <LemonButton
                type="secondary"
                size="small"
                icon={<IconLightBulb />}
                sideIcon={null}
                disabledReason={disabledReason}
            >
                Recommendations
            </LemonButton>
            {message && <span className="text-secondary">{message}</span>}
            {state === 'no_connected_source' && (
                <RecommendationsConnectGoogleAdsButton type="secondary" location="section_empty" />
            )}
        </>
    )
}
