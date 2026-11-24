import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { SOURCE_PREFILL_PARAM } from '../Broadcasts/broadcastAudiencePrefill'
import { TRIGGER_PREFILL_PARAM, type WorkflowTriggerConfig } from './workflowTriggerPrefill'

// pinned: URL search param, the email template scene links to /workflows/new with it
export const MESSAGE_TEMPLATE_PREFILL_PARAM = 'messageTemplate'
// The person picks the event in the editor.
export const EVENT_TRIGGER_WITH_NO_EVENT: WorkflowTriggerConfig = { type: 'event', filters: {} }

export function urlForEventWorkflowWithEmailTemplate(templateId: string): string {
    return combineUrl(urls.workflowNew(), {
        [TRIGGER_PREFILL_PARAM]: JSON.stringify(EVENT_TRIGGER_WITH_NO_EVENT),
        [MESSAGE_TEMPLATE_PREFILL_PARAM]: templateId,
        // pinned: analytics entry_source value
        [SOURCE_PREFILL_PARAM]: 'email_template',
    }).url
}
