import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { WORKFLOW_BRIEF_HANDOFF_PARAM } from 'lib/utils/workflowDraftHandoff'
import { AiFirstCreateScene } from 'scenes/max/aiFirstCreate/AiFirstCreateScene'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { NEW_WORKFLOW_HANDOFF } from './newWorkflowHandoff'
import { newWorkflowLogic } from './newWorkflowLogic'
import { NewWorkflowModal } from './NewWorkflowModal'
import { NEW_WORKFLOW_SUGGESTIONS } from './workflowAgentContext'

/** The AI-first "New workflow" screen: the composer first, with the template modal behind the escape hatch. */
export function NewWorkflowAgent(): JSX.Element {
    const { openEditorFromAiComposer } = useActions(newWorkflowLogic)
    const { searchParams } = useValues(router)

    return (
        <>
            {/* A new handoff on an open composer remounts it, so it takes the brief the URL names. */}
            <AiFirstCreateScene
                key={searchParams[WORKFLOW_BRIEF_HANDOFF_PARAM]}
                handoff={NEW_WORKFLOW_HANDOFF}
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
