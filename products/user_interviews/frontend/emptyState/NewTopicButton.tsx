import { useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { NEW_TOPIC_PROMPT, NEW_TOPIC_SUGGESTIONS } from '../newTopicMaxTool'

/** The empty state's primary action: the same Max-driven topic creation as the scene's "New topic" button. */
export function NewTopicButton(): JSX.Element {
    const { isMaxAvailable } = useValues(maxGlobalLogic)
    const { openMax } = useMaxTool({
        identifier: 'create_user_interview_topic',
        context: {},
        initialMaxPrompt: NEW_TOPIC_PROMPT,
        suggestions: NEW_TOPIC_SUGGESTIONS,
        // `openMax` is null only when the tool is inactive, so without this the button stays
        // enabled on an instance without PostHog AI and opens a panel saying it isn't set up.
        active: isMaxAvailable,
    })

    return (
        <LemonButton
            type="primary"
            icon={<IconSparkles />}
            className="self-start"
            data-attr="user-research-empty-state-new-topic"
            onClick={() => openMax?.()}
            disabledReason={openMax ? undefined : 'PostHog AI is unavailable here'}
        >
            Create your first topic
        </LemonButton>
    )
}
