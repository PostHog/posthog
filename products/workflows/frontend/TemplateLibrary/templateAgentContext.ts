import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { DESIGNING_EMAIL_TEMPLATES_SKILL, EMAIL_TEMPLATE_MCP_TOOLS } from '../agentContext.generated'
import { MessageTemplate } from './types'

// Each visible chip and the hidden payload items it stands for share a dismiss group, so closing
// the chip actually detaches the payload instead of only hiding the chip.
const SKILL_DISMISS_GROUP = 'template-scene-skill'
const EDITOR_STATE_DISMISS_GROUP = 'template-scene-state'

// All static strings below are build-time constants from our own repo (skill markdown + tool
// descriptions), which is what makes them safe to attach as trusted `instructions` items.
const PREAMBLE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value:
        'The user has the PostHog email template editor open. The full designing-email-templates skill and the ' +
        'complete email template MCP tool catalog are included in this context - you already have everything ' +
        'needed to act. Do not spend turns discovering tools or reading skill files: call the listed tools ' +
        'directly, and use the exec `info <tool>` command only when you need a full input schema.',
}

const SKILL_CONTENT_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value:
        `Skill ${DESIGNING_EMAIL_TEMPLATES_SKILL.name} (embedded, including its design-JSON and ` +
        `design-guidelines references): ${DESIGNING_EMAIL_TEMPLATES_SKILL.content}`,
}

const EDITOR_STATE_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: EDITOR_STATE_DISMISS_GROUP,
    value:
        'The message_template_editor_state item is the current, possibly unsaved editor state of the email ' +
        'template the user has open - prefer it over a fetched template when reading. Use ' +
        'workflows-get-email-template only when you need the persisted state. An oversized design may be ' +
        'elided from this state; read it with workflows-get-email-template.',
}

const TOOL_CONTEXT_ITEMS: AttachedContextItem[] = EMAIL_TEMPLATE_MCP_TOOLS.map((tool) => ({
    type: 'instructions',
    hidden: true,
    dismissGroup: SKILL_DISMISS_GROUP,
    value: `MCP tool ${tool.name}: ${tool.description}`,
}))

const SKILL_CHIP_CONTEXT_ITEM: AttachedContextItem = {
    type: 'skill',
    key: DESIGNING_EMAIL_TEMPLATES_SKILL.name,
    label: 'Designing email templates skill',
    dismissGroup: SKILL_DISMISS_GROUP,
}

export function templateAgentHeadlines(id: string): string[] {
    return id === 'new' ? ['What template would you like to build?'] : ['How can we improve this email template?']
}

/** Serialized editor state beyond this budget gets its design elided (see `serializeTemplateEditorState`). */
export const TEMPLATE_EDITOR_STATE_MAX_CHARS = 64_000

const DESIGN_ELIDED_MARKER = '[design elided for size: read it with workflows-get-email-template]'

/**
 * Serialize the live template for agent context, bounding the payload that rides along with every
 * message: the rendered email html is dropped when a design is present (the server re-renders html
 * from the design on every save, so it is derived weight), and if the result still exceeds
 * `TEMPLATE_EDITOR_STATE_MAX_CHARS` the design itself is swapped for a fetch hint. Elision keeps
 * the JSON parseable, which blind truncation would not.
 */
export function serializeTemplateEditorState(template: MessageTemplate): string {
    const prepared = structuredClone(template)
    const email = prepared.content?.email as Record<string, unknown> | undefined
    // Templates without a design keep their html, because it is the only body they have.
    if (email?.design && email.html) {
        delete email.html
    }
    const serialized = JSON.stringify(prepared)
    if (serialized.length <= TEMPLATE_EDITOR_STATE_MAX_CHARS) {
        return serialized
    }
    if (email?.design) {
        email.design = DESIGN_ELIDED_MARKER
    }
    return JSON.stringify(prepared)
}

/**
 * The default agent context for the email template editor scene: the embedded
 * designing-email-templates skill, the email template MCP tool catalog, and the current template
 * (a visible ref for saved templates plus the live editor state so unsaved edits are visible to
 * the agent).
 */
export function buildTemplateAgentContext(template: MessageTemplate | null, id: string): AttachedContextItem[] {
    const items: AttachedContextItem[] = [
        PREAMBLE_CONTEXT_ITEM,
        SKILL_CHIP_CONTEXT_ITEM,
        SKILL_CONTENT_CONTEXT_ITEM,
        ...TOOL_CONTEXT_ITEMS,
        EDITOR_STATE_CONTEXT_ITEM,
    ]
    if (id !== 'new') {
        items.push({
            type: 'message_template',
            key: id,
            label: template?.name || 'Current template',
            dismissGroup: EDITOR_STATE_DISMISS_GROUP,
        })
    }
    if (template) {
        items.push({
            type: 'message_template_editor_state',
            hidden: true,
            dismissGroup: EDITOR_STATE_DISMISS_GROUP,
            value: serializeTemplateEditorState(template),
        })
    }
    return items
}
