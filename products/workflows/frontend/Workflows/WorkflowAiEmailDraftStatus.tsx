import { useActions, useValues } from 'kea'

import { AiEmailDraftStatus } from '../MessageAudience/AiEmailDraftStatus'
import { hogFlowEditorLogic } from './hogflows/hogFlowEditorLogic'
import { EMAIL_ACTION_ID } from './workflowEmailPrefill'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

export function WorkflowAiEmailDraftStatus(props: WorkflowLogicProps): JSX.Element | null {
    const { aiEmailDraftStatus } = useValues(workflowLogic(props))
    const { setSelectedNodeId } = useActions(hogFlowEditorLogic(props))
    if (!aiEmailDraftStatus) {
        return null
    }
    if (aiEmailDraftStatus.status === 'applied') {
        return <AiEmailDraftStatus status="applied" onReview={() => setSelectedNodeId(EMAIL_ACTION_ID)} />
    }
    return <AiEmailDraftStatus {...aiEmailDraftStatus} />
}
