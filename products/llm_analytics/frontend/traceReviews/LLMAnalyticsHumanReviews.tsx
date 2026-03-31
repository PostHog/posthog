import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { urls } from '~/scenes/urls'

import { LLMAnalyticsReviewQueues } from '../reviewQueues/LLMAnalyticsReviewQueues'
import { LLMAnalyticsScoreDefinitions } from '../scoreDefinitions/LLMAnalyticsScoreDefinitions'
import { LLMAnalyticsReviews } from './LLMAnalyticsReviews'

const HUMAN_REVIEWS_TAB_PARAM = 'human_reviews_tab'

export function LLMAnalyticsHumanReviews({ tabId }: { tabId?: string }): JSX.Element {
    const { searchParams } = useValues(router)
    const { push } = useActions(router)

    const activeHumanReviewsTab =
        searchParams[HUMAN_REVIEWS_TAB_PARAM] === 'reviews'
            ? 'reviews'
            : searchParams[HUMAN_REVIEWS_TAB_PARAM] === 'scorers'
              ? 'scorers'
              : 'queues'

    const tabs: LemonTab<string>[] = [
        {
            key: 'queues',
            label: 'Queues',
            content: <LLMAnalyticsReviewQueues tabId={tabId} />,
            link: combineUrl(urls.llmAnalyticsReviews(), {
                ...searchParams,
                [HUMAN_REVIEWS_TAB_PARAM]: undefined,
            }).url,
        },
        {
            key: 'reviews',
            label: 'Reviews',
            content: <LLMAnalyticsReviews tabId={tabId} />,
            link: combineUrl(urls.llmAnalyticsReviews(), {
                ...searchParams,
                [HUMAN_REVIEWS_TAB_PARAM]: 'reviews',
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
                        [HUMAN_REVIEWS_TAB_PARAM]:
                            tab === 'reviews' ? 'reviews' : tab === 'scorers' ? 'scorers' : undefined,
                    }).url
                )
            }
        />
    )
}
