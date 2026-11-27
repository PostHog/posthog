import { useActions, useValues } from 'kea'

import { Text } from '@posthog/quill'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityCard } from './AiVisibilityCard'
import { ContentAutopilotKeywordAddForm } from './ContentAutopilotKeywordAddForm'
import { ContentAutopilotKeywordModifiers } from './ContentAutopilotKeywordModifiers'
import { ContentAutopilotKeywordReportTable } from './ContentAutopilotKeywordReportTable'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { ContentAutopilotKeywordsModal } from './ContentAutopilotKeywordsModal'
import { ContentAutopilotKeywordsSkeleton } from './ContentAutopilotKeywordsSkeleton'
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
            <AiVisibilityBanner
                type="error"
                action={{ children: 'Try again', onClick: loadKeywords, loading: keywordsLoading }}
            >
                Couldn't load your keywords. Try again, and if it keeps happening contact support.
            </AiVisibilityBanner>
        )
    }
    if (!keywords) {
        return <ContentAutopilotKeywordsSkeleton />
    }
    if (keywords.length === 0) {
        return (
            <div className="max-w-3xl" data-attr="content-autopilot-keywords-empty">
                <AiVisibilityCard title="No keywords yet">
                    <div className="flex flex-col gap-3">
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Keywords are the words and phrases you want to be known for, like a product category or a
                            feature. Add your first keywords, or ask PostHog to suggest some.
                        </Text>
                        <div>
                            <ContentAutopilotKeywordSuggestButton />
                        </div>
                        <ContentAutopilotKeywordAddForm />
                    </div>
                    <ContentAutopilotKeywordSuggestModal />
                </AiVisibilityCard>
            </div>
        )
    }

    return (
        <section className="@container/keywords flex flex-col gap-4" data-attr="content-autopilot-keywords">
            <ContentAutopilotKeywordReportTable />
            <ContentAutopilotKeywordModifiers />
            <ContentAutopilotKeywordsModal />
            <ContentAutopilotKeywordSuggestModal />
        </section>
    )
}
