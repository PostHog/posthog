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
