import type {
    EmailDomainDnsHostApi,
    EmailDomainStatusRecordApi,
} from 'products/integrations/frontend/generated/api.schemas'

export interface SetupPromptInput {
    domain: string
    mailFromSubdomain: string
    projectId: number
    integrationId: number
    pageUrl: string
    dnsHost: EmailDomainDnsHostApi | null
    supportsDomainConnect: boolean
    records: EmailDomainStatusRecordApi[]
    agentUsesBrowser: boolean
}

const formatRecord = (record: EmailDomainStatusRecordApi): string => {
    const priority = record.priority != null ? ` (priority ${record.priority})` : ''
    return `- ${record.type}  ${record.hostname}  ->  ${record.value}${priority}`
}

const buildMcpPrompt = ({
    domain,
    mailFromSubdomain,
    projectId,
    integrationId,
    dnsHost,
    supportsDomainConnect,
    records,
}: SetupPromptInput): string => {
    const hostLine = dnsHost
        ? `- DNS host detected from the nameservers: ${dnsHost.name}${supportsDomainConnect ? ' (supports Domain Connect)' : ''}`
        : '- DNS host: unknown. Ask me where the DNS for this domain is managed before you change anything.'
    return [
        `Get the email sending domain ${domain} verified for PostHog Workflows. If you have the setting-up-an-email-domain skill, follow it.`,
        '',
        'Facts',
        `- PostHog project id: ${projectId}`,
        `- Email sender (integration) id: ${integrationId}. It already exists. Do not create it again with integrations-create; re-creating it marks it unverified.`,
        `- Domain: ${domain}`,
        `- MAIL FROM subdomain: ${mailFromSubdomain}.${domain}. It applies to every sender on this domain. Never pick a new one; changing it needs new DNS records and breaks the other senders until they are published.`,
        hostLine,
        '',
        'Steps',
        `1. Read the current records and status with integrations-email-status-retrieve (project ${projectId}, integration ${integrationId}). If the PostHog MCP is not available, use the records listed below.`,
        '2. If the host supports Domain Connect, call integrations-domain-connect-check-retrieve, then integrations-domain-connect-apply-url-create to get an approval URL. Show me that URL and wait for me to approve it in my browser. Do not open it yourself.',
        '3. Otherwise add the records at the DNS host yourself. Paste names and values exactly. If the host appends the domain to the name field, enter only the part before the domain. Always publish both SPF TXT records, merging include:amazonses.com into an existing SPF record at the same name instead of adding a second one. Never add a second _dmarc record; keep an existing one.',
        '4. Call integrations-email-verify-create once. Then poll integrations-email-status-retrieve every 30 seconds until the status is "verified". Stop after 30 minutes and tell me which records are still missing.',
        "5. Only change the sender's display name or MAIL FROM subdomain with integrations-email-partial-update if I ask. Send the sender's current email unchanged.",
        '',
        'Records',
        ...records.map(formatRecord),
    ].join('\n')
}

const buildBrowserPrompt = ({ domain, dnsHost, records, pageUrl }: SetupPromptInput): string => {
    const hostLine = dnsHost
        ? `The DNS for this domain is managed at ${dnsHost.name}. Open ${dnsHost.dns_settings_url} in the browser. I am already signed in.`
        : 'Ask me where the DNS for this domain is managed, then open that provider in the browser. I am already signed in.'
    return [
        `Use the browser to add the DNS records below for ${domain}, then verify the domain in PostHog.`,
        '',
        hostLine,
        '',
        'Rules',
        `- Never add a second _dmarc record. If a TXT record already exists at _dmarc.${domain}, keep it and skip ours.`,
        '- Do not delete or edit any existing record except to merge include:amazonses.com into an SPF record that already exists at the same name.',
        '- If the provider appends the domain to the name field, enter only the part before the domain.',
        '- Show me the list of records you added before you leave the DNS page.',
        `- Then open ${pageUrl} and click "Check again". Wait until the page says the domain is ready to send. Tell me if any record is still missing after 10 minutes.`,
        '',
        'Records',
        ...records.map(formatRecord),
    ].join('\n')
}

export const buildSetupPrompt = (input: SetupPromptInput): string =>
    input.agentUsesBrowser ? buildBrowserPrompt(input) : buildMcpPrompt(input)
