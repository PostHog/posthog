export type StepProduct = 'workflows' | 'core' | 'support' | 'customer_analytics' | 'tasks' | 'signals'

export type StepCategory =
    | 'messaging'
    | 'ai'
    | 'flow'
    | 'posthog_data'
    | 'support'
    | 'customer_analytics'
    | 'crm'
    | 'marketing'
    | 'analytics'
    | 'ads'
    | 'developer'
    | 'data'

export type StepAttribution = {
    product: StepProduct | null
    vendor: string | null
    operation: string | null
    category: StepCategory | null
}

const posthogStep = (product: StepProduct, category: StepCategory): StepAttribution => ({
    product,
    vendor: null,
    operation: null,
    category,
})

const thirdPartyStep = (
    vendor: string,
    category: StepCategory,
    { operation }: { operation?: string } = {}
): StepAttribution => ({ product: null, vendor, operation: operation ?? null, category })

export const STEP_ATTRIBUTION: Record<string, StepAttribution> = {
    'template-email': posthogStep('workflows', 'messaging'),
    'template-twilio': thirdPartyStep('Twilio', 'messaging'),
    'template-slack': thirdPartyStep('Slack', 'messaging'),
    'template-webhook': posthogStep('workflows', 'developer'),
    'template-native-push': posthogStep('workflows', 'messaging'),
    'template-posthog-create-task': posthogStep('tasks', 'ai'),
    'template-posthog-run-scout': posthogStep('signals', 'ai'),
    'template-posthog-classify': posthogStep('workflows', 'ai'),
    'step-delay': posthogStep('workflows', 'flow'),
    'step-wait_until_time_window': posthogStep('workflows', 'flow'),
    'step-wait_until_condition': posthogStep('workflows', 'flow'),
    'step-conditional_branch': posthogStep('workflows', 'flow'),
    'step-random_cohort_branch': posthogStep('workflows', 'flow'),
    'template-posthog-set-variable': posthogStep('workflows', 'flow'),
    'template-posthog-capture': posthogStep('core', 'posthog_data'),
    'template-posthog-update-person-properties': posthogStep('core', 'posthog_data'),
    'template-posthog-group-identify': posthogStep('core', 'posthog_data'),
    'template-posthog-get-ticket': posthogStep('support', 'support'),
    'template-posthog-update-ticket': posthogStep('support', 'support'),
    'template-posthog-send-ticket-message': posthogStep('support', 'support'),
    'template-posthog-create-customer-task': posthogStep('customer_analytics', 'customer_analytics'),
    'template-posthog-create-account': posthogStep('customer_analytics', 'customer_analytics'),
    'template-posthog-get-account': posthogStep('customer_analytics', 'customer_analytics'),
    'template-posthog-tag-account': posthogStep('customer_analytics', 'customer_analytics'),
    'template-posthog-update-account-relationships': posthogStep('customer_analytics', 'customer_analytics'),
    'template-posthog-update-account-property': posthogStep('customer_analytics', 'customer_analytics'),
    'template-activecampaign': thirdPartyStep('ActiveCampaign', 'marketing'),
    'template-airtable': thirdPartyStep('Airtable', 'data'),
    'template-attio': thirdPartyStep('Attio', 'crm'),
    'template-avo': thirdPartyStep('Avo', 'analytics'),
    'template-aws-kinesis': thirdPartyStep('Amazon Web Services', 'data'),
    'template-beehiiv': thirdPartyStep('beehiiv', 'marketing'),
    'template-braze': thirdPartyStep('Braze', 'marketing'),
    'template-brevo': thirdPartyStep('Brevo', 'marketing'),
    'segment-calliper-cloud-actions': thirdPartyStep('Calliper', 'analytics'),
    'template-clearbit': thirdPartyStep('Clearbit', 'data'),
    'template-clickup': thirdPartyStep('ClickUp', 'developer'),
    'template-close': thirdPartyStep('Close', 'crm'),
    'template-customerio': thirdPartyStep('Customer.io', 'marketing'),
    'template-discord': thirdPartyStep('Discord', 'messaging'),
    'template-engage-so': thirdPartyStep('Engage.so', 'marketing'),
    'template-github': thirdPartyStep('GitHub', 'developer'),
    'template-gitlab': thirdPartyStep('GitLab', 'developer'),
    'template-gleap': thirdPartyStep('Gleap', 'crm'),
    'template-google-ads': thirdPartyStep('Google', 'ads', { operation: 'Ads conversions' }),
    'template-google-cloud-storage': thirdPartyStep('Google', 'data', { operation: 'Cloud Storage' }),
    'template-google-pubsub': thirdPartyStep('Google', 'data', { operation: 'Pub/Sub' }),
    'segment-actions-hilo': thirdPartyStep('Hilo', 'analytics'),
    'template-hubspot': thirdPartyStep('HubSpot', 'crm', { operation: 'Create contact' }),
    'template-hubspot-company': thirdPartyStep('HubSpot', 'crm', { operation: 'Create company' }),
    'template-hubspot-event': thirdPartyStep('HubSpot', 'crm', { operation: 'Send event' }),
    'template-intercom': thirdPartyStep('Intercom', 'crm', { operation: 'Update contact' }),
    'template-intercom-event': thirdPartyStep('Intercom', 'crm', { operation: 'Send event' }),
    'template-june': thirdPartyStep('June.so', 'analytics'),
    'template-klaviyo-event': thirdPartyStep('Klaviyo', 'marketing', { operation: 'Send event' }),
    'template-klaviyo-user': thirdPartyStep('Klaviyo', 'marketing', { operation: 'Update contact' }),
    'template-klime': thirdPartyStep('Klime', 'analytics'),
    'template-knock': thirdPartyStep('Knock', 'messaging'),
    'segment-actions-koala-cloud': thirdPartyStep('Koala', 'analytics'),
    'template-kudosity-sms': thirdPartyStep('Kudosity', 'messaging'),
    'segment-actions-launchdarkly': thirdPartyStep('LaunchDarkly', 'analytics'),
    'template-linear': thirdPartyStep('Linear', 'developer'),
    'template-linkedin-ads': thirdPartyStep('LinkedIn Ads Conversions', 'ads'),
    'template-loops': thirdPartyStep('Loops', 'marketing', { operation: 'Update contact' }),
    'template-loops-event': thirdPartyStep('Loops', 'marketing', { operation: 'Send event' }),
    'template-mailgun-send-email': thirdPartyStep('Mailgun', 'messaging'),
    'template-mailjet-create-contact': thirdPartyStep('Mailjet', 'marketing', { operation: 'Add contact' }),
    'template-mailjet-update-contact-list': thirdPartyStep('Mailjet', 'marketing', {
        operation: 'Update contact list',
    }),
    'template-make': thirdPartyStep('Make', 'developer'),
    'template-microsoft-teams': thirdPartyStep('Microsoft', 'messaging'),
    'template-onesignal': thirdPartyStep('OneSignal', 'messaging'),
    'template-pagerduty': thirdPartyStep('PagerDuty', 'developer'),
    'segment-actions-playerzero-cloud': thirdPartyStep('PlayerZero', 'analytics'),
    'segment-actions-podscribe': thirdPartyStep('Podscribe', 'ads'),
    'template-posthog-replicator': posthogStep('core', 'posthog_data'),
    'template-retain': thirdPartyStep('Retain', 'analytics'),
    'segment-actions-revx': thirdPartyStep('RevX', 'ads'),
    'template-rudderstack': thirdPartyStep('RudderStack', 'data'),
    'template-salesforce-create': thirdPartyStep('Salesforce', 'crm', { operation: 'Create object' }),
    'template-salesforce-lookup': thirdPartyStep('Salesforce', 'crm', { operation: 'Look up object' }),
    'template-salesforce-update': thirdPartyStep('Salesforce', 'crm', { operation: 'Update object' }),
    'template-sendgrid': thirdPartyStep('SendGrid', 'marketing'),
    'template-snapchat-ads': thirdPartyStep('Snap', 'ads'),
    'segment-actions-stackadapt-cloud': thirdPartyStep('StackAdapt', 'ads'),
    'template-unify': thirdPartyStep('Unify', 'analytics'),
    'template-userlist': thirdPartyStep('Userlist', 'marketing'),
    'template-whatsapp': thirdPartyStep('Meta', 'messaging'),
    'template-zapier': thirdPartyStep('Zapier', 'developer'),
    'template-zendesk': thirdPartyStep('Zendesk', 'crm'),
}

const CATEGORY_BY_TEMPLATE_TAG: Record<string, StepCategory> = {
    CRM: 'crm',
    'Email Marketing': 'marketing',
    Marketing: 'marketing',
    'User Engagement Platforms': 'marketing',
    Advertisement: 'ads',
    Analytics: 'analytics',
    'Error tracking': 'developer',
    'Monitoring & Alerts': 'developer',
    Productivity: 'developer',
    Communication: 'messaging',
    'SMS & Push Notifications': 'messaging',
}

export function unclassifiedDestinationAttribution(name: string, tags: string[]): StepAttribution {
    const mappedTag = tags.find((tag) => tag in CATEGORY_BY_TEMPLATE_TAG)
    return {
        product: null,
        vendor: name,
        operation: null,
        category: mappedTag ? CATEGORY_BY_TEMPLATE_TAG[mappedTag] : null,
    }
}
