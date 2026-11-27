import { useActions, useValues } from 'kea'

import { IconPencil } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { ContentAutopilotKeywordSuggestButton } from './ContentAutopilotKeywordSuggestButton'

/** The Keywords tab's actions. Hidden until there are keywords, because the empty state carries its own. */
export const ContentAutopilotKeywordsActions = (): JSX.Element | null => {
    const { keywords } = useValues(contentAutopilotKeywordsLogic)
    const { openKeywordsModal } = useActions(contentAutopilotKeywordsLogic)

    if (!keywords?.length) {
        return null
    }
    return (
        <div className="flex flex-wrap items-center gap-2">
            <ContentAutopilotKeywordSuggestButton />
            <Button variant="outline" onClick={openKeywordsModal} data-attr="content-autopilot-keywords-manage">
                <IconPencil />
                Manage keywords
            </Button>
        </div>
    )
}
