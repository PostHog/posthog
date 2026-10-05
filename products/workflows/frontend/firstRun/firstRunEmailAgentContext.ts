import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import type { HogFlowTemplateApi } from '../generated/api.schemas'
import type { OpenEmail, OpenEmailPosition } from './firstRunMakeItYoursLogic'

const DISMISS_GROUP = 'workflows-first-run-email'
const MAX_CONTEXT_CHARS = 64_000

export function buildFirstRunEmailAgentContext(
    template: Pick<HogFlowTemplateApi, 'id' | 'name'>,
    openEmail: OpenEmail,
    position: OpenEmailPosition
): AttachedContextItem[] {
    const dismissGroup = `${DISMISS_GROUP}:${template.id}`
    const { subject, preheader, text, html, design } = openEmail.email
    const state = {
        source: 'workflows_first_run_email',
        template_id: template.id,
        template_name: template.name,
        email_id: openEmail.id,
        position: position.index,
        total: position.total,
        email: {
            subject,
            preheader,
            text,
            body_mode: html ? 'visual' : 'plaintext',
            ...(html ? (design ? { design } : { html }) : {}),
        },
    }
    let serialized = JSON.stringify(state)
    if (serialized.length > MAX_CONTEXT_CHARS && html) {
        serialized = JSON.stringify({
            ...state,
            email: { subject, preheader, text, html, body_mode: 'visual' },
            omitted_content: 'The email design exceeds the context budget. The rendered HTML is attached instead.',
        })
    }
    if (serialized.length > MAX_CONTEXT_CHARS) {
        serialized = JSON.stringify({
            ...state,
            template_name: template.name.slice(0, 256),
            email: {
                body_mode: html ? 'visual' : 'plaintext',
                subject: subject?.slice(0, 1000),
                preheader: preheader?.slice(0, 1000),
                text: text?.slice(0, 6000),
            },
            omitted_content: 'The email design or body exceeds the context budget and is not attached.',
        })
    }
    if (serialized.length > MAX_CONTEXT_CHARS) {
        serialized = JSON.stringify({
            source: state.source,
            position: position.index,
            total: position.total,
            omitted_content: 'The email content and identifiers exceed the context budget and are not attached.',
        })
    }
    return [
        {
            type: 'instructions',
            hidden: true,
            dismissGroup,
            value:
                'The user has Make it yours open in the Workflows first run. The text context item with source ' +
                'workflows_first_run_email describes the selected email and its position in the sequence. ' +
                'The latest attached state wins over earlier emails or edits in the conversation. Load the ' +
                'designing-email-templates skill for email design guidance. This email is unsaved and has no ' +
                'workflow or library template ID that tools can update. Suggest changes to this email for the ' +
                'user to apply in the editor. Do not create a workflow, save a library template, enable anything, ' +
                'or send email unless the user explicitly asks.',
        },
        {
            type: 'skill',
            key: 'designing-email-templates',
            label: 'Designing email templates skill',
            dismissGroup,
        },
        {
            type: 'text',
            value: serialized,
            label: `Email ${position.index} of ${position.total}: ${subject?.slice(0, 200) || 'Untitled email'}`,
            dismissGroup,
        },
    ]
}
