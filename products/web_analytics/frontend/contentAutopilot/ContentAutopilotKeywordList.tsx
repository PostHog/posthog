import { useActions, useValues } from 'kea'

import { LemonSnack } from '@posthog/lemon-ui'

import { PagePerformanceCard } from 'scenes/web-analytics/PagePerformanceCard'
import { PagePerformanceCardHeader } from 'scenes/web-analytics/PagePerformanceCardHeader'

import type { AEOKeywordApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotKeywordAddForm } from './ContentAutopilotKeywordAddForm'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { ContentAutopilotKeywordSuggestButton } from './ContentAutopilotKeywordSuggestButton'
import { MAX_KEYWORDS } from './keywordsReport'

export const ContentAutopilotKeywordList = ({ keywords }: { keywords: AEOKeywordApi[] }): JSX.Element => {
    const { keywordRemoving } = useValues(contentAutopilotKeywordsLogic)
    const { removeKeyword } = useActions(contentAutopilotKeywordsLogic)

    return (
        <PagePerformanceCard className="min-w-0">
            <PagePerformanceCardHeader
                title={`Keywords (${keywords.length} of ${MAX_KEYWORDS})`}
                actions={<ContentAutopilotKeywordSuggestButton size="small" />}
            />
            <div className="flex flex-col gap-3 p-3" data-attr="content-autopilot-keywords-list">
                <div className="flex flex-wrap gap-1">
                    {keywords.map((keyword) => (
                        <LemonSnack
                            key={keyword.id}
                            onClose={keywordRemoving[keyword.id] ? undefined : () => removeKeyword(keyword)}
                            className={keywordRemoving[keyword.id] ? 'opacity-50' : undefined}
                            data-attr="content-autopilot-keywords-remove"
                        >
                            {keyword.keyword}
                        </LemonSnack>
                    ))}
                </div>
                <ContentAutopilotKeywordAddForm />
            </div>
        </PagePerformanceCard>
    )
}
