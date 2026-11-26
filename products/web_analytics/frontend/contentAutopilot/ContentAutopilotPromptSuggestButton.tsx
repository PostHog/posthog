import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { Button, Spinner } from '@posthog/quill'

import { contentAutopilotPromptSuggestionsLogic } from './contentAutopilotPromptSuggestionsLogic'

export const ContentAutopilotPromptSuggestButton = ({
    type = 'secondary',
    disabledReason,
}: {
    type?: 'primary' | 'secondary'
    disabledReason?: string
}): JSX.Element => {
    const { job } = useValues(contentAutopilotPromptSuggestionsLogic)
    const { openSuggest } = useActions(contentAutopilotPromptSuggestionsLogic)

    return (
        // A pending job keeps the button clickable, because it opens the dialog that shows the progress.
        <Button
            variant={type === 'primary' ? 'primary' : 'outline'}
            onClick={openSuggest}
            disabledReason={disabledReason}
            data-attr="content-autopilot-prompts-suggest"
        >
            {job?.status === 'pending' ? <Spinner /> : <IconSparkles />}
            {job?.status === 'pending'
                ? 'Suggesting prompts'
                : job?.status === 'completed' && job.suggestions.length > 0
                  ? `Review suggestions (${job.suggestions.length})`
                  : 'Suggest prompts'}
        </Button>
    )
}
