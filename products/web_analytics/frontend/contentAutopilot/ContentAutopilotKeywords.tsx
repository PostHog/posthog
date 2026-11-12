import { useActions, useValues } from 'kea'

import { LemonBanner, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { ContentAutopilotKeywordAddForm } from './ContentAutopilotKeywordAddForm'
import { ContentAutopilotKeywordList } from './ContentAutopilotKeywordList'
import { ContentAutopilotKeywordModifiers } from './ContentAutopilotKeywordModifiers'
import { ContentAutopilotKeywordReportTable } from './ContentAutopilotKeywordReportTable'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { ContentAutopilotKeywordSuggestButton } from './ContentAutopilotKeywordSuggestButton'
import { ContentAutopilotKeywordSuggestModal } from './ContentAutopilotKeywordSuggestModal'
import { ContentAutopilotPromptsDisabled } from './ContentAutopilotPromptsDisabled'

export const ContentAutopilotKeywords = (): JSX.Element => {
    const { keywords, keywordsLoading, keywordsError } = useValues(contentAutopilotKeywordsLogic)
    const { loadKeywords } = useActions(contentAutopilotKeywordsLogic)

    if (keywordsError === 'forbidden') {
        return <ContentAutopilotPromptsDisabled />
    }
    if (keywordsError === 'failed') {
        return (
            <LemonBanner
                type="error"
                action={{ children: 'Try again', onClick: loadKeywords, loading: keywordsLoading }}
            >
                Couldn't load your keywords. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }
    if (!keywords) {
        return <LemonSkeleton className="h-32 w-full" />
    }
    if (keywords.length === 0) {
        return (
            <LemonCard hoverEffect={false} className="p-4 max-w-3xl" data-attr="content-autopilot-keywords-empty">
                <h4 className="m-0">No keywords yet</h4>
                <p className="m-0 mt-1 mb-3 text-muted">
                    Keywords are the words and phrases you want to be known for, like a product category or a feature.
                    For each one, PostHog shows how often the AI engines search for it and use it in their answers, and
                    how often those answers mention or cite you. Add your first keywords, or ask PostHog to suggest
                    some.
                </p>
                <div className="mb-3">
                    <ContentAutopilotKeywordSuggestButton type="primary" />
                </div>
                <ContentAutopilotKeywordAddForm />
                <ContentAutopilotKeywordSuggestModal />
            </LemonCard>
        )
    }

    return (
        <section className="@container/keywords flex flex-col gap-4" data-attr="content-autopilot-keywords">
            <ContentAutopilotKeywordList keywords={keywords} />
            <ContentAutopilotKeywordReportTable />
            <ContentAutopilotKeywordModifiers />
            <ContentAutopilotKeywordSuggestModal />
        </section>
    )
}
