import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { contentAutopilotKeywordSuggestionsLogic } from './contentAutopilotKeywordSuggestionsLogic'

export const ContentAutopilotKeywordSuggestButton = ({
    type = 'secondary',
    size,
}: {
    type?: 'primary' | 'secondary'
    size?: 'small'
}): JSX.Element => {
    const { job } = useValues(contentAutopilotKeywordSuggestionsLogic)
    const { openSuggest } = useActions(contentAutopilotKeywordSuggestionsLogic)

    return (
        <LemonButton
            type={type}
            size={size}
            icon={job?.status === 'pending' ? <Spinner /> : <IconSparkles />}
            onClick={openSuggest}
            data-attr="content-autopilot-keywords-suggest"
        >
            {job?.status === 'pending'
                ? 'Suggesting keywords'
                : job?.status === 'completed' && job.suggestions.length > 0
                  ? `Review suggestions (${job.suggestions.length})`
                  : 'Suggest keywords'}
        </LemonButton>
    )
}
