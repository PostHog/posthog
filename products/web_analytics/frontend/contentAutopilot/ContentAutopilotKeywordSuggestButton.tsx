import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button, Spinner } from '@posthog/quill'

import { contentAutopilotKeywordSuggestionsLogic } from './contentAutopilotKeywordSuggestionsLogic'

export const ContentAutopilotKeywordSuggestButton = (): JSX.Element => {
    const { job } = useValues(contentAutopilotKeywordSuggestionsLogic)
    const { openSuggest } = useActions(contentAutopilotKeywordSuggestionsLogic)

    return (
        // Not `loading`: that would block the click that reopens the dialog to show the progress.
        <Button variant="outline" onClick={openSuggest} data-attr="content-autopilot-keywords-suggest">
            {job?.status === 'pending' ? <Spinner /> : <IconSparkles />}
            {job?.status === 'pending'
                ? 'Suggesting keywords'
                : job?.status === 'completed' && job.suggestions.length > 0
                  ? `Review suggestions (${job.suggestions.length})`
                  : 'Suggest keywords'}
        </Button>
    )
}
