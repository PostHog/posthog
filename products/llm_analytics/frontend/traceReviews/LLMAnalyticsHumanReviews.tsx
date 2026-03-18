import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { urls } from '~/scenes/urls'

import { LLMAnalyticsScoreDefinitions } from '../scoreDefinitions/LLMAnalyticsScoreDefinitions'
import { LLMAnalyticsReviews } from './LLMAnalyticsReviews'

const HUMAN_REVIEWS_TAB_PARAM = 'human_reviews_tab'

export function LLMAnalyticsHumanReviews({ tabId }: { tabId?: string }): JSX.Element {
    const { searchParams } = useValues(router)
    const { push } = useActions(router)

    const activeHumanReviewsTab = searchParams[HUMAN_REVIEWS_TAB_PARAM] === 'scorers' ? 'scorers' : 'reviews'

    const tabs: LemonTab<string>[] = [
        {
            key: 'reviews',
            label: 'Reviews',
            content: <LLMAnalyticsReviews tabId={tabId} />,
            link: combineUrl(urls.llmAnalyticsReviews(), {
                ...searchParams,
                [HUMAN_REVIEWS_TAB_PARAM]: undefined,
            }).url,
        },
        {
            key: 'scorers',
            label: 'Scorers',
            content: <LLMAnalyticsScoreDefinitions tabId={tabId} />,
            link: combineUrl(urls.llmAnalyticsReviews(), {
                ...searchParams,
                [HUMAN_REVIEWS_TAB_PARAM]: 'scorers',
            }).url,
        },
    ]

    return (
        <LemonTabs
            activeKey={activeHumanReviewsTab}
            tabs={tabs}
            onChange={(tab) =>
                push(
                    combineUrl(urls.llmAnalyticsReviews(), {
                        ...searchParams,
                        [HUMAN_REVIEWS_TAB_PARAM]: tab === 'scorers' ? 'scorers' : undefined,
                    }).url
                )
            }
        />
    )
}
