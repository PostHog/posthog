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
    const { promptActiveUpdating } = useValues(contentAutopilotPromptsLogic)
    const { setPromptActive } = useActions(contentAutopilotPromptsLogic)

    return (
        <LemonSwitch
            checked={active}
            onChange={(checked) => setPromptActive(promptId, checked)}
            loading={!!promptActiveUpdating[promptId]}
            label={label}
            aria-label={active ? 'Turn prompt off' : 'Turn prompt on'}
            data-attr="content-autopilot-prompt-active-toggle"
        />
    )
}
