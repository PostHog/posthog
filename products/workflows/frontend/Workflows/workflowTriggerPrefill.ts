import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { SOURCE_PREFILL_PARAM, parseBroadcastAudiencePrefill } from '../Broadcasts/broadcastAudiencePrefill'
import type { EmailDraftRequestApi } from '../generated/api.schemas'
import { DRAFT_SOURCE_PARAM } from '../MessageAudience/aiEmailDraft'
import { EMAIL_PREFILL_PARAM, MessageDraft } from '../MessageAudience/messageDrafts'
import { HogFlowTriggerSchema } from './hogflows/steps/types'
import type { HogFlowAction } from './hogflows/types'

export type WorkflowTriggerConfig = Extract<HogFlowAction, { type: 'trigger' }>['config']

export const TRIGGER_PREFILL_PARAM = 'trigger'
// pinned: URL search param, the email template scene links to /workflows/new with it
export const MESSAGE_TEMPLATE_PREFILL_PARAM = 'messageTemplate'
// The person picks the event in the editor.
export const EVENT_TRIGGER_WITH_NO_EVENT: WorkflowTriggerConfig = { type: 'event', filters: {} }

export function urlForNewWorkflowWithTrigger(
    config: WorkflowTriggerConfig,
    source?: string,
    email?: MessageDraft,
    draftSource?: EmailDraftRequestApi
): string {
    return combineUrl(urls.workflowNew(), {
        [TRIGGER_PREFILL_PARAM]: JSON.stringify(config),
        ...(source ? { [SOURCE_PREFILL_PARAM]: source } : {}),
        ...(email ? { [EMAIL_PREFILL_PARAM]: JSON.stringify(email) } : {}),
        ...(draftSource ? { [DRAFT_SOURCE_PARAM]: JSON.stringify(draftSource) } : {}),
    }).url
}

/** A new workflow that sends a copy of an email template's published email when an event happens. */
export function urlForEventWorkflowWithEmailTemplate(templateId: string): string {
    return combineUrl(urls.workflowNew(), {
        [TRIGGER_PREFILL_PARAM]: JSON.stringify(EVENT_TRIGGER_WITH_NO_EVENT),
        [MESSAGE_TEMPLATE_PREFILL_PARAM]: templateId,
        // pinned: analytics entry_source value
        [SOURCE_PREFILL_PARAM]: 'email_template',
    }).url
}

// kea-router hands over JSON-looking search params already parsed, so accept an object too.
export function parseWorkflowTriggerPrefill(raw: unknown): WorkflowTriggerConfig | null {
    if (!raw) {
        return null
    }
    try {
        const result = HogFlowTriggerSchema.safeParse(typeof raw === 'string' ? JSON.parse(raw) : raw)
        if (!result.success) {
            return null
        }
        const config = result.data as WorkflowTriggerConfig
        if (config.type !== 'batch' || !config.filters.properties?.length) {
            return config
        }
        // A batch audience gets the same check as a broadcast link, so a filter the backend drops can't widen it.
        const properties = parseBroadcastAudiencePrefill(config.filters.properties)
        return properties ? { ...config, filters: { ...config.filters, properties } } : null
    } catch {
        return null
    }
}
