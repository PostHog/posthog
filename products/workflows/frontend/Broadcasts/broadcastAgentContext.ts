import type { AiFirstSuggestion } from 'scenes/max/aiFirstCreate/AiFirstCreateScene'

import { AttachedContextItem } from 'products/posthog_ai/frontend/api/types'

// Own dismiss group: a dismissal is global and never resets, so a chip closed elsewhere must not strip this page.
const NEW_BROADCAST_DISMISS_GROUP = 'new-broadcast-composer'

const BUILDING_WORKFLOWS_SKILL = 'building-workflows'

export const NEW_BROADCAST_AGENT_HEADLINES: string[] = ['What would you like to send?']

export const NEW_BROADCAST_SUGGESTIONS: AiFirstSuggestion[] = [
    {
        title: 'Announce a feature',
        description: 'Tell your users about something new',
        prompt: 'Announce our newest feature to all our users',
    },
    {
        title: 'Monthly product update',
        description: 'A roundup of what changed this month',
        prompt: 'Write a monthly product update email for all users',
    },
    {
        title: 'Invite to an event',
        description: 'Ask people to join a webinar or meetup',
        prompt: 'Invite our users to an upcoming webinar and ask them to register',
    },
    {
        title: 'Planned maintenance',
        description: 'Let people know about downtime ahead of time',
        prompt: 'Tell all users about planned maintenance and when it will happen',
    },
]

// Static text, so it is safe as a trusted instruction. Launching belongs to the wizard's review step.
const DRAFT_FIRST_CONTEXT_ITEM: AttachedContextItem = {
    type: 'instructions',
    hidden: true,
    dismissGroup: NEW_BROADCAST_DISMISS_GROUP,
    value:
        `The user is starting a new broadcast from a description. Load the ${BUILDING_WORKFLOWS_SKILL} skill, ` +
        'then make broadcasts-create your first workflows tool call and do not ask clarifying questions first: ' +
        'a name, the audience, and a first draft of the email. The broadcast wizard opens the draft the moment it ' +
        'exists, so refine the email afterwards with workflows-patch-action-email. Do not add steps, do not enable ' +
        'or publish it, and do not attach a schedule or start a run. The user picks the timing and launches it ' +
        'from the wizard.',
}

const SKILL_CHIP_CONTEXT_ITEM: AttachedContextItem = {
    type: 'skill',
    key: BUILDING_WORKFLOWS_SKILL,
    label: 'Building workflows skill',
    dismissGroup: NEW_BROADCAST_DISMISS_GROUP,
    // Not dismissible: the page only advances once the broadcast exists.
    dismissible: false,
}

export function buildNewBroadcastComposerContext(): AttachedContextItem[] {
    return [SKILL_CHIP_CONTEXT_ITEM, DRAFT_FIRST_CONTEXT_ITEM]
}
