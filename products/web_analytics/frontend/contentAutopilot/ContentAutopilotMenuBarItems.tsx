import { useActions } from 'kea'

import { IconGear, IconPlus, IconSparkles } from '@posthog/icons'

import { SceneMenuBarItem } from '~/layout/scenes/components/SceneMenuBar'

import { contentAutopilotLogic } from './contentAutopilotLogic'
import { contentAutopilotPromptsLogic } from './contentAutopilotPromptsLogic'
import { contentAutopilotPromptSuggestionsLogic } from './contentAutopilotPromptSuggestionsLogic'

/** AI visibility's rows in the Web analytics View menu. */
export const ContentAutopilotMenuBarItems = (): JSX.Element => {
    const { setWorkspaceTab } = useActions(contentAutopilotLogic)
    const { openAddPrompts } = useActions(contentAutopilotPromptsLogic)
    const { openSuggest } = useActions(contentAutopilotPromptSuggestionsLogic)

    return (
        <>
            <SceneMenuBarItem
                onClick={openAddPrompts}
                opensFloatingUi
                data-attr="content-autopilot-menubar-add-prompts"
            >
                <IconPlus />
                Add prompts
            </SceneMenuBarItem>
            <SceneMenuBarItem
                onClick={openSuggest}
                opensFloatingUi
                data-attr="content-autopilot-menubar-suggest-prompts"
            >
                <IconSparkles />
                Suggest prompts
            </SceneMenuBarItem>
            <SceneMenuBarItem
                onClick={() => setWorkspaceTab('settings')}
                data-attr="content-autopilot-menubar-settings"
            >
                <IconGear />
                AI visibility settings
            </SceneMenuBarItem>
        </>
    )
}
