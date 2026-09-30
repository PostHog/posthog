import type { AiFirstSuggestion } from 'scenes/max/aiFirstCreate/AiFirstCreateScene'

import type { HogFunctionTemplateWithSubTemplateType } from '~/types'

// pinned: CDP destination template ids. Each of these tools messages users from the data PostHog sends it,
// which is the job a workflow does inside PostHog. A renamed template id must be updated here too.
export const WORKFLOWS_CROSS_SELL_TEMPLATE_IDS: ReadonlySet<string> = new Set([
    'template-customerio',
    'template-braze',
    'template-klaviyo-user',
    'template-klaviyo-event',
    'template-loops',
    'template-loops-event',
    'template-brevo',
    'template-sendgrid',
    'template-mailgun-send-email',
    'template-mailjet-create-contact',
    'template-mailjet-update-contact-list',
    'template-activecampaign',
    'template-engage-so',
    'template-userlist',
    'template-knock',
    'template-kudosity-sms',
    'template-onesignal',
    'template-mailchimp',
])

// pinned: the `source` URL param value and analytics property that tie a composer run back to this dialog
export const WORKFLOWS_CROSS_SELL_SOURCE = 'cdp_destination_cross_sell'

/**
 * Only a real destination qualifies. Alert sub-templates reuse a destination's id under another `type`, and
 * hidden templates are Workflows' own building blocks.
 */
export function isWorkflowsCrossSellTemplate(template: HogFunctionTemplateWithSubTemplateType): boolean {
    return (
        template.type === 'destination' &&
        !template.sub_template_id &&
        template.status !== 'hidden' &&
        WORKFLOWS_CROSS_SELL_TEMPLATE_IDS.has(template.id)
    )
}

const EMAIL_SUGGESTIONS: AiFirstSuggestion[] = [
    {
        title: 'Welcome new signups',
        description: 'A short email sequence over the first week',
        prompt: 'Send a welcome email sequence to new signups over their first week',
    },
    {
        title: 'Finish onboarding',
        description: 'Nudge people who started but never completed it',
        prompt: 'Remind users who started onboarding but never finished it',
    },
    {
        title: 'Win back inactive users',
        description: 'Reach out after 30 days of silence',
        prompt: 'Re-engage users who have been inactive for 30 days',
    },
]

const SMS_SUGGESTIONS: AiFirstSuggestion[] = [
    {
        title: 'Welcome new signups',
        description: 'A short text message after signup',
        prompt: 'Send new users a welcome SMS when they sign up',
    },
    {
        title: 'Recover abandoned checkouts',
        description: 'A text an hour after checkout stalls',
        prompt: 'Send an SMS reminder to users who start checkout but do not complete it within an hour',
    },
    {
        title: 'Win back inactive users',
        description: 'A text after 30 days of silence',
        prompt: 'Send an SMS to users who have been inactive for 30 days',
    },
]

const NOTIFICATION_SUGGESTIONS: AiFirstSuggestion[] = [
    {
        title: 'Welcome new signups',
        description: 'Greet people after their first session',
        prompt: 'Notify new users with a welcome message after they sign up',
    },
    {
        title: 'Bring users back',
        description: 'Reach out after 7 days of inactivity',
        prompt: 'Notify users who have been inactive for 7 days',
    },
    {
        title: 'Celebrate a milestone',
        description: 'A message when a key action completes',
        prompt: 'Notify users when they complete their first purchase',
    },
]

const SMS_TEMPLATE_IDS = new Set(['template-kudosity-sms'])
const NOTIFICATION_TEMPLATE_IDS = new Set(['template-onesignal', 'template-knock'])

/** Suggestions match the channel the person was about to set up, so the first draft reads as a replacement. */
export function suggestionsForTemplate(templateId: string): AiFirstSuggestion[] {
    if (SMS_TEMPLATE_IDS.has(templateId)) {
        return SMS_SUGGESTIONS
    }
    if (NOTIFICATION_TEMPLATE_IDS.has(templateId)) {
        return NOTIFICATION_SUGGESTIONS
    }
    return EMAIL_SUGGESTIONS
}
