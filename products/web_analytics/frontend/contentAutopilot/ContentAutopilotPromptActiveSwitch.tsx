import { useActions, useValues } from 'kea'

import { LemonSwitch } from '@posthog/lemon-ui'

import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'

export const ContentAutopilotPromptActiveSwitch = ({
    promptId,
    active,
    label,
}: {
    promptId: string
    active: boolean
    label?: string
}): JSX.Element => {
    const { promptActiveUpdating, setupContext, promptLimitReached } = useValues(contentAutopilotPromptsLogic)
    const { setPromptActive } = useActions(contentAutopilotPromptsLogic)

    return (
        <LemonSwitch
            checked={active}
            onChange={(checked) => setPromptActive(promptId, checked)}
            loading={!!promptActiveUpdating[promptId]}
            disabledReason={
                !active && promptLimitReached && setupContext
                    ? `You're tracking ${setupContext.active_prompts} prompts, and this project can track up to ${setupContext.max_active_prompts}. Turn off some prompts first.`
                    : undefined
            }
            label={label}
            aria-label={active ? 'Turn prompt off' : 'Turn prompt on'}
            data-attr="content-autopilot-prompt-active-toggle"
        />
    )
}
