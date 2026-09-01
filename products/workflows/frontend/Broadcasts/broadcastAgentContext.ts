import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { WORKFLOWS_MCP_TOOLS } from '../generated/agentContext'
import type { BroadcastEmailValue } from './broadcastWizardLogic'

// Each visible chip and the hidden payload items it stands for share a dismiss group, so closing
// the chip actually detaches the payload instead of only hiding the chip.
const BROADCAST_STATE_DISMISS_GROUP = 'broadcast-scene-state'
const GUIDANCE_DISMISS_GROUP = 'broadcast-scene-guidance'

// The wizard only edits one email step, so the agent needs the email-focused slice of the
// workflows tool catalog rather than the full graph-editing set.
const BROADCAST_TOOL_NAMES = [
    'workflows-get',
    'workflows-patch-action-email',
    'workflows-list-email-templates',
    'workflows-get-email-template',
]

const TOOL_CONTEXT_ITEMS: AttachedContextItem[] = WORKFLOWS_MCP_TOOLS.filter((tool) =>
    BROADCAST_TOOL_NAMES.includes(tool.name)
).map((tool) => ({
    type: 'instructions',
    hidden: true,
    dismissGroup: GUIDANCE_DISMISS_GROUP,
    value: `MCP tool ${tool.name}: ${tool.description}`,
}))

export const BROADCAST_AGENT_HEADLINES: string[] = [
    'How can I help with this broadcast?',
    'What should this email say?',
]

// pinned: must match EMAIL_ACTION_ID in broadcastWizardLogic — the wizard builds every broadcast
// flow with this email step id, and the agent addresses its patches to it.
const EMAIL_ACTION_ID = 'email_node'

/** Email designs beyond this budget get elided so the context payload stays bounded. */
export const EMAIL_STATE_MAX_CHARS = 32_000

/**
 * Serialize the wizard's live email value for agent context. The rendered html is dropped when a
 * design is present (the server re-renders html from the design on every patch, so it is derived
 * weight), and an oversized design is swapped for a fetch hint so the JSON stays parseable.
 */
export function serializeBroadcastEmailState(email: BroadcastEmailValue): string {
    const prepared: Record<string, unknown> = { ...email }
    if (prepared.design && prepared.html) {
        delete prepared.html
    }
    const serialized = JSON.stringify(prepared)
    if (serialized.length <= EMAIL_STATE_MAX_CHARS) {
        return serialized
    }
    prepared.design = '[design elided for size: read it with workflows-get]'
    return JSON.stringify(prepared)
}

// All static strings below are build-time constants from our own repo, which is what makes them
// safe to attach as trusted `instructions` items — never interpolate ids or user text into them.
const PREAMBLE_BASE =
    'The user has the PostHog broadcast wizard open. A broadcast is a workflow (hog flow) of kind ' +
    `"broadcast" with a single email step whose action id is "${EMAIL_ACTION_ID}". The ` +
    'broadcast_email_editor_state item is the current, possibly unsaved email in the editor - prefer it ' +
    'over a fetched definition when reading. '

const PREAMBLE_UNSAVED =
    PREAMBLE_BASE +
    'This broadcast has not been saved yet, so there is no flow to patch. Help with subject lines, ' +
    'copy, and structure in chat; the draft flow is created once the user continues past a wizard step, ' +
    'after which you can apply edits directly.'

const PREAMBLE_SAVED =
    PREAMBLE_BASE +
    "To change the email, call workflows-patch-action-email with id set to the attached hog_flow item's " +
    `key and action_id "${EMAIL_ACTION_ID}" - the wizard picks the edit up automatically. Do not use ` +
    'graph-editing tools to restructure the flow: the wizard owns the trigger/email/exit shape.'

/**
 * The default agent context for the broadcast wizard: guidance on how to edit the broadcast's
 * email step, the email-focused MCP tool slice, and the live email editor state (plus a visible
 * ref chip once the draft flow exists).
 */
export function buildBroadcastAgentContext(
    broadcastId: string | null,
    name: string,
    email: BroadcastEmailValue
): AttachedContextItem[] {
    const items: AttachedContextItem[] = [
        {
            type: 'instructions',
            hidden: true,
            dismissGroup: GUIDANCE_DISMISS_GROUP,
            value: broadcastId ? PREAMBLE_SAVED : PREAMBLE_UNSAVED,
        },
        ...TOOL_CONTEXT_ITEMS,
    ]
    if (broadcastId) {
        items.push({
            type: 'hog_flow',
            key: broadcastId,
            label: name || 'Current broadcast',
            dismissGroup: BROADCAST_STATE_DISMISS_GROUP,
        })
    }
    items.push({
        type: 'broadcast_email_editor_state',
        hidden: true,
        dismissGroup: BROADCAST_STATE_DISMISS_GROUP,
        value: serializeBroadcastEmailState(email),
    })
    return items
}
