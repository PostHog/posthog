// Template categories split these tools across "Email Marketing", "Customer Success" and "Communication",
// so the list is explicit. It holds tools whose job Workflows email covers. SMS and WhatsApp tools stay out,
// because Workflows sends those through a provider and has no native channel of its own.
export const MESSAGING_DESTINATION_TEMPLATE_IDS: ReadonlySet<string> = new Set([
    'template-activecampaign',
    'template-beehiiv',
    'template-braze',
    'template-brevo',
    'template-customerio',
    'template-engage-so',
    'template-intercom',
    'template-intercom-event',
    'template-klaviyo-event',
    'template-klaviyo-user',
    'template-knock',
    'template-loops',
    'template-loops-event',
    'template-mailgun-send-email',
    'template-mailjet-create-contact',
    'template-mailjet-update-contact-list',
    'template-onesignal',
    'template-sendgrid',
    'template-userlist',
])

export function isMessagingDestinationTemplate(templateId: string): boolean {
    return MESSAGING_DESTINATION_TEMPLATE_IDS.has(templateId)
}

// Matches MAX_PICKED_EVENTS in the data suggestions service, which rejects longer lists.
export const MAX_WORKFLOW_EVENTS = 5

/** The custom events in a destination's filters that a workflow can start from. PostHog's own `$` events, like the
 * `$identify` and `$pageview` defaults, say nothing about what the team wants to email on. */
export function workflowEventsFromFilters(
    filters: { events?: { id?: unknown }[] | null } | null | undefined
): string[] {
    const events = (filters?.events ?? [])
        .map((event) => event.id)
        .filter((id): id is string => typeof id === 'string' && id.length > 0 && !id.startsWith('$'))
    return [...new Set(events)].slice(0, MAX_WORKFLOW_EVENTS)
}
