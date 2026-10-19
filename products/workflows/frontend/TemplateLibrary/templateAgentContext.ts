import type { AiFirstSuggestion } from 'scenes/max/aiFirstCreate/AiFirstCreateScene'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

import { isCodeManagedTemplate } from './codeManagedTemplate'
import { MessageTemplate } from './types'

// Own dismiss groups: a dismissal is global and never resets, so a chip closed on a workflow must not strip this page.
// The picked template has its own group so removing its attachment clears the pick and nothing else.
const NEW_TEMPLATE_DISMISS_GROUP = 'new-email-template-composer'
export const PICKED_TEMPLATE_DISMISS_GROUP = 'new-email-template-picked'

const DESIGNING_EMAIL_TEMPLATES_SKILL = 'designing-email-templates'

export const NEW_TEMPLATE_AGENT_HEADLINES: string[] = ['What email would you like to create today?']

/** Prefills the composer when a saved template is picked. The person finishes the sentence. */
export const PICKED_TEMPLATE_PROMPT = 'Using this template, create a new email template that '

export const NEW_TEMPLATE_SUGGESTIONS: AiFirstSuggestion[] = [
    {
        title: 'Welcome email',
        description: 'Greet new signups and point them to a first step',
        prompt: 'Create a welcome email for new signups that introduces the product and points them to a first step',
    },
    {
        title: 'Product update',
        description: 'Announce a new feature with one call to action',
        prompt: 'Create a product update email that announces a new feature with one call to action',
    },
    {
        title: 'Finish onboarding',
        description: 'Remind people who have not finished setup',
        prompt: 'Create an email that reminds people who have not finished setup, with a link to continue',
    },
    {
        title: 'Monthly newsletter',
        description: 'A short intro and three highlights',
        prompt: 'Create a monthly newsletter email with a short intro and three highlights',
    },
    {
        title: 'Win back inactive users',
        description: 'Reach out after 30 days of silence',
        prompt: 'Create a win-back email for people who have not used the product in 30 days',
    },
    {
        title: 'Event invitation',
        description: 'Invite people to a webinar with a sign-up button',
        prompt: 'Create an event invitation email for a webinar with the date, time and a sign-up button',
    },
]

// All static strings below are our own build-time constants, which is what makes them safe to attach
// as trusted `instructions` items. The picked template rides an untrusted item, and the instruction
// refers to it by type only, so no user-entered name reaches trusted context.
const TOOLING_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: NEW_TEMPLATE_DISMISS_GROUP,
    value:
        `The user is starting a new email template from a description. Load the ${DESIGNING_EMAIL_TEMPLATES_SKILL} ` +
        'skill before your first tool call; it covers the email design JSON schema and the design guidelines. Act ' +
        'through the exec workflows-*-email-template commands (workflows-create-email-template, ' +
        'workflows-get-email-template, workflows-patch-email-template, workflows-update-email-template, ' +
        'workflows-show-email-template). Do not search for tools; use the exec `info <tool>` command when you ' +
        'need a full input schema.',
}

// The fastest useful outcome from nothing is a saved template in the editor, refined with the agent alongside.
const DRAFT_FIRST_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: NEW_TEMPLATE_DISMISS_GROUP,
    value:
        'If an email_template context item is attached, call workflows-get-email-template with its id first and use ' +
        'that design as the starting point; keep its layout and styling unless the user asks for changes, and never ' +
        'modify the attached template itself. Then make workflows-create-email-template your next tool call and do ' +
        'not ask clarifying questions first: save a name, a subject, a plain-text fallback and a first design. The ' +
        'editor opens the template the moment it exists and reloads external edits live, so refine the design ' +
        'afterwards with workflows-patch-email-template and finish with workflows-show-email-template.',
}

const SKILL_CHIP_CONTEXT_ITEM: AttachedContextItem = {
    type: 'skill',
    key: DESIGNING_EMAIL_TEMPLATES_SKILL,
    label: 'Designing email templates skill',
    dismissGroup: NEW_TEMPLATE_DISMISS_GROUP,
    // Not dismissible: the page only advances once the template exists.
    dismissible: false,
}

/** The picked template as untrusted context: a ref the agent fetches, plus the html the composer shows as a thumbnail. */
export function pickedTemplateContextItem(template: MessageTemplate): AttachedContextItem {
    return {
        type: 'email_template',
        key: template.id,
        label: template.name || 'Unnamed template',
        previewHtml: template.content?.email?.html,
        dismissGroup: PICKED_TEMPLATE_DISMISS_GROUP,
    }
}

// Per template: a dismissal is global and never resets, so closing one template's chip must not strip another's.
function codeManagedDismissGroup(template: MessageTemplate): string {
    return `code-managed-email-template:${template.id}`
}

// Static, like the items above: the key and the source come from an upload, so the instruction names the
// email_template_source item instead of quoting them.
const CODE_MANAGED_INSTRUCTIONS: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    value:
        'The user has a PostHog email template open that is managed by code: its content comes from a file in a ' +
        'repository, and the email_template_source item names its key and file. Load the ' +
        `${DESIGNING_EMAIL_TEMPLATES_SKILL} skill before your first tool call and follow its "Code-managed ` +
        'templates" section. Never change this template with workflows-update-email-template or ' +
        'workflows-patch-email-template. When its repository is not in your workspace, do not call ' +
        'workflows-request-email-template-change either, because it refuses calls from PostHog AI. Instead, tell ' +
        'the user to click "Edit with your agent" on this page, describe the change, and click "Run with PostHog ' +
        'Code", which opens a pull request, or copy the prompt into their own coding agent.',
}

function templateSourceSummary(template: MessageTemplate): string {
    const fields: [string, string | null | undefined][] = [
        ['managed_by', template.managed_by],
        ['key', template.key],
        ['source_repository', template.source_repository],
        ['source_path', template.source_path],
        ['source_ref', template.source_ref],
    ]
    return fields
        .filter(([, value]) => !!value)
        .map(([name, value]) => `${name}: ${value}`)
        .join('; ')
}

/** What the agent needs before its first tool call on a template managed by code; null for any other template. */
export function buildCodeManagedTemplateContext(template: MessageTemplate): AttachedContextItem[] | null {
    if (!isCodeManagedTemplate(template)) {
        return null
    }
    const dismissGroup = codeManagedDismissGroup(template)
    return [
        { ...CODE_MANAGED_INSTRUCTIONS, dismissGroup },
        // Not dismissible: closing a chip also dismisses its key everywhere, and every page shares this skill's key.
        { ...SKILL_CHIP_CONTEXT_ITEM, dismissGroup },
        {
            type: 'email_template',
            key: template.id,
            label: template.name || 'Unnamed template',
            dismissGroup,
        },
        {
            type: 'email_template_source',
            hidden: true,
            value: templateSourceSummary(template),
            dismissGroup,
        },
    ]
}

/** Skill pointer plus the draft-first instruction, and the picked template when there is one. */
export function buildNewTemplateComposerContext(pickedTemplate: MessageTemplate | null): AttachedContextItem[] {
    const items = [TOOLING_CONTEXT_ITEM, SKILL_CHIP_CONTEXT_ITEM, DRAFT_FIRST_CONTEXT_ITEM]
    return pickedTemplate ? [...items, pickedTemplateContextItem(pickedTemplate)] : items
}
