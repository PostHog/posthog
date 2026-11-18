import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { contentAutopilotPromptSuggestionsLogic } from './contentAutopilotPromptSuggestionsLogic'

export const ContentAutopilotPromptSuggestButton = ({
    type = 'secondary',
    size,
    disabledReason,
}: {
    type?: 'primary' | 'secondary'
    size?: 'small'
    disabledReason?: string
}): JSX.Element => {
    const { job } = useValues(contentAutopilotPromptSuggestionsLogic)
    const { openSuggest } = useActions(contentAutopilotPromptSuggestionsLogic)

    return (
        <LemonButton
            type={type}
            size={size}
            icon={job?.status === 'pending' ? <Spinner /> : <IconSparkles />}
            onClick={openSuggest}
            disabledReason={disabledReason}
            data-attr="content-autopilot-prompts-suggest"
        >
            {job?.status === 'pending'
                ? 'Suggesting prompts'
                : job?.status === 'completed' && job.suggestions.length > 0
                  ? `Review suggestions (${job.suggestions.length})`
                  : 'Suggest prompts'}
        </LemonButton>
    )
}
