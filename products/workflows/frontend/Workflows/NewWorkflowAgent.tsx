import { useActions, useValues } from 'kea'

import { AiFirstCreateScene } from 'scenes/max/aiFirstCreate/AiFirstCreateScene'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { workflowHandoffInFolder } from './newWorkflowHandoff'
import { newWorkflowLogic } from './newWorkflowLogic'
import { NewWorkflowModal } from './NewWorkflowModal'
import { NEW_WORKFLOW_SUGGESTIONS } from './workflowAgentContext'

/** The AI-first "New workflow" screen: the composer first, with the template modal behind the escape hatch. */
export function NewWorkflowAgent(): JSX.Element {
    const { openEditorFromAiComposer } = useActions(newWorkflowLogic)
    const { composerFolder } = useValues(newWorkflowLogic)

    return (
        <>
            <AiFirstCreateScene
                handoff={workflowHandoffInFolder(composerFolder)}
                banner="We're trialling building workflows with PostHog AI. Describe what you want and it drafts the workflow for you to refine."
                escapeHatchLabel="Use the editor instead"
                onEscapeHatch={openEditorFromAiComposer}
                suggestions={NEW_WORKFLOW_SUGGESTIONS}
                suggestionIcon={iconForType('workflows')}
                dataAttr="new-workflow-agent"
            />
            <NewWorkflowModal />
        </>
    )
}
