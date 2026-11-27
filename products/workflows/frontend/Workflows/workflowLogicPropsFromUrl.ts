import { SOURCE_PREFILL_PARAM } from '../Broadcasts/broadcastAudiencePrefill'
import { DRAFT_SOURCE_PARAM } from '../MessageAudience/aiEmailDraft'
import { EMAIL_PREFILL_PARAM } from '../MessageAudience/messageDrafts'
import { MESSAGE_TEMPLATE_PREFILL_PARAM } from './emailTemplateWorkflowPrefill'
import type { WorkflowLogicProps } from './workflowLogic'
import { TRIGGER_PREFILL_PARAM } from './workflowTriggerPrefill'

function asJsonProp(raw: unknown): string | undefined {
    return raw && typeof raw !== 'string' ? JSON.stringify(raw) : (raw as string | undefined)
}

export function workflowLogicPropsFromUrl(
    id: string | undefined,
    searchParams: Record<string, any>
): WorkflowLogicProps {
    const messageTemplateId = searchParams[MESSAGE_TEMPLATE_PREFILL_PARAM]
    const entrySource = searchParams[SOURCE_PREFILL_PARAM]
    return {
        id,
        templateId: searchParams.templateId as string | undefined,
        editTemplateId: searchParams.editTemplateId as string | undefined,
        triggerPrefill: asJsonProp(searchParams[TRIGGER_PREFILL_PARAM]),
        emailPrefill: asJsonProp(searchParams[EMAIL_PREFILL_PARAM]),
        messageTemplateId: typeof messageTemplateId === 'string' ? messageTemplateId : undefined,
        draftSource: asJsonProp(searchParams[DRAFT_SOURCE_PARAM]),
        entrySource: typeof entrySource === 'string' ? entrySource : undefined,
    }
}
