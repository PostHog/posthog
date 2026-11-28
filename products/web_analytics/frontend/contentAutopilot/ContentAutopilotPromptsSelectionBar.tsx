import { useActions, useValues } from 'kea'

import { Button, Text } from '@posthog/quill'

import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'

/** What to do with the prompts picked in the list. Shows only while some are picked. */
export const ContentAutopilotPromptsSelectionBar = (): JSX.Element | null => {
    const { selectedPromptIds } = useValues(contentAutopilotPromptsLogic)
    const { openSetTopic, clearPromptSelection } = useActions(contentAutopilotPromptsLogic)

    if (selectedPromptIds.length === 0) {
        return null
    }
    return (
        <div
            className="flex flex-wrap items-center gap-2 rounded-md border px-3 py-2"
            data-attr="content-autopilot-prompts-selection"
        >
            <Text size="xs" weight="semibold" render={<span className="m-0" />}>
                {selectedPromptIds.length} selected
            </Text>
            <Button variant="outline" size="sm" onClick={openSetTopic} data-attr="content-autopilot-prompts-set-topic">
                Set topic
            </Button>
            <Button
                variant="link-muted"
                size="sm"
                onClick={clearPromptSelection}
                data-attr="content-autopilot-prompts-selection-clear"
            >
                Clear selection
            </Button>
        </div>
    )
}
