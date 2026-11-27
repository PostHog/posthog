import { useActions, useValues } from 'kea'

import { Switch } from '@posthog/quill'

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
        <Switch
            checked={active}
            onCheckedChange={(checked) => setPromptActive(promptId, checked)}
            disabledReason={
                promptActiveUpdating[promptId]
                    ? 'Saving…'
                    : !active && promptLimitReached && setupContext
                      ? `You're tracking ${setupContext.active_prompts} prompts, and this project can track up to ${setupContext.max_active_prompts}. Turn off some prompts first.`
                      : undefined
            }
            aria-label={active ? 'Turn prompt off' : 'Turn prompt on'}
            data-attr="content-autopilot-prompt-active-toggle"
        >
            {label}
        </Switch>
    )
}
