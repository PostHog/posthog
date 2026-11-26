import { useValues } from 'kea'

import { ContentAutopilotKeywordsActions } from './ContentAutopilotKeywordsActions'
import { contentAutopilotLogic } from './contentAutopilotLogic'
import { contentAutopilotPromptDetailLogic } from './contentAutopilotPromptDetailLogic'
import { ContentAutopilotPromptsActions } from './ContentAutopilotPromptsActions'

/** The open AI visibility tab's actions, for the scene header. */
export const ContentAutopilotSceneActions = (): JSX.Element | null => {
    const { workspaceTab, onboardingOpen } = useValues(contentAutopilotLogic)
    const { promptId } = useValues(contentAutopilotPromptDetailLogic)

    const actions =
        promptId || onboardingOpen ? null : workspaceTab === 'prompts' ? (
            <ContentAutopilotPromptsActions />
        ) : workspaceTab === 'keywords' ? (
            <ContentAutopilotKeywordsActions />
        ) : null

    // The scene header sits outside the AI visibility root, so it scopes quill's tokens itself.
    return actions ? (
        <div className="contents" data-quill>
            {actions}
        </div>
    ) : null
}
