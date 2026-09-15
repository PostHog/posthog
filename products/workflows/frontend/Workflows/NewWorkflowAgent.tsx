import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { MAX_SIDE_PANEL_ID } from 'scenes/max/components/PhaiSidePanelChat'

import { runnerPanelLogic } from 'products/posthog_ai/frontend/api/logics'
import { SidePanelRunner } from 'products/posthog_ai/frontend/api/runner'

import { newWorkflowAgentLogic } from './newWorkflowAgentLogic'
import { newWorkflowLogic } from './newWorkflowLogic'
import { NewWorkflowModal } from './NewWorkflowModal'

/** The AI-first "New workflow" screen: the side panel's runner rendered full page, with a way back to the editor. */
export function NewWorkflowAgent(): JSX.Element {
    useMountedLogic(newWorkflowAgentLogic)
    const { openEditorFromAiComposer } = useActions(newWorkflowLogic)
    const { activeCreation } = useValues(runnerPanelLogic({ panelId: MAX_SIDE_PANEL_ID }))

    return (
        <div className="flex flex-col grow min-h-0" data-attr="new-workflow-agent">
            <SidePanelRunner panelId={MAX_SIDE_PANEL_ID} />
            {!activeCreation && (
                <div className="flex justify-center shrink-0 pb-4">
                    <LemonButton
                        type="tertiary"
                        size="small"
                        data-attr="new-workflow-agent-open-editor"
                        onClick={openEditorFromAiComposer}
                    >
                        Build it in the editor instead
                    </LemonButton>
                </div>
            )}
            <NewWorkflowModal />
        </div>
    )
}
