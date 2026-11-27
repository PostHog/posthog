import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { ContentAutopilotPromptSuggestButton } from './ContentAutopilotPromptSuggestButton'

/** The prompts tab's actions. It reads the logics itself, so it can sit in the tab or in the scene header. */
export const ContentAutopilotPromptsActions = (): JSX.Element => {
    const { openAddPrompts } = useActions(contentAutopilotPromptsLogic)

    return (
        <div className="flex flex-wrap items-center gap-2">
            <ContentAutopilotPromptSuggestButton />
            <Button variant="primary" onClick={openAddPrompts} data-attr="content-autopilot-prompts-add">
                <IconPlus />
                Add prompts
            </Button>
        </div>
    )
}
