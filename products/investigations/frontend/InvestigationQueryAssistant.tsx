import { useActions, useValues } from 'kea'

import { aiShellLogic } from '~/layout/ai/aiShellLogic'

import { useAttachedContext, useMcpToolApplyBack } from 'products/posthog_ai/frontend/api/logics'

import { InvestigationQueryAssistantProps, investigationQueryAssistantLogic } from './investigationQueryAssistantLogic'
import { InvestigationQueryComposer } from './InvestigationQueryComposer'
import { investigationQueryContext } from './queryAssistantHelpers'

export function InvestigationQueryAssistant(props: InvestigationQueryAssistantProps): JSX.Element | null {
    const logic = investigationQueryAssistantLogic(props)
    const { request, activeRequestId } = useValues(logic)
    const { receiveProposal } = useActions(logic)
    const { isMaxAvailable, isPhaiSandboxFlagOn } = useValues(aiShellLogic)
    const available = props.editable && isMaxAvailable && isPhaiSandboxFlagOn
    const active = available && request?.id === activeRequestId
    useAttachedContext(active && request ? investigationQueryContext(props.document, request) : null)
    useMcpToolApplyBack({
        tools: ['execute-sql'],
        targetKey: 'investigation-query:' + props.scope + ':' + (request?.id ?? 'idle'),
        active,
        onApply: (_event, { innerInput }) => receiveProposal(innerInput),
    })
    return available ? <InvestigationQueryComposer {...props} /> : null
}
