const DNS_HOST_GOTCHAS: Record<string, string> = {
    Cloudflare: 'Keep the proxy off (grey cloud) on the CNAME records. Proxied CNAMEs do not work for DKIM.',
    'Route 53': 'Route 53 asks for the full record name. Paste the name as shown, including your domain.',
    Namecheap:
        'Namecheap adds your domain to the Host field. Paste only the part before your domain, so "feedback" and not "feedback.acme.com".',
}

const GENERIC_GOTCHA =
    'If the name field already ends with your domain, paste only the part before it. Otherwise paste the full name.'

export const dnsHostGotcha = (hostName: string | null): string => DNS_HOST_GOTCHAS[hostName ?? ''] ?? GENERIC_GOTCHA
