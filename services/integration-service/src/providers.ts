// The provider manifest: which integration apps exist, and which credential fields each
// one holds. Only keys listed here are ever served.
//
// Kept in code rather than discovered by listing Secrets Manager, so the service needs no
// ListSecrets permission, a mistyped key name fails as an explicit "unknown key", and
// adding a credential is a reviewed change. One secret holds every field, so the provider
// grouping is for metrics, rotation reporting and review, not a storage boundary.
//
// Key names are the existing Django env var names, so the cutover is a 1:1 mapping.
//
// ONLY OUTBOUND CREDENTIALS BELONG HERE. There is no per-deployment allowlist, so every
// key below is readable by every deployment holding a signing key. For a secret PostHog
// presents to a third party that is no expansion, since the pod already had its own copy
// in its environment. For an inbound-request authenticator, such as a webhook signing
// secret, it would hand any compromised pod the ability to forge requests to us.

export interface ProviderDefinition {
    /** Credential field names, i.e. the keys this provider owns inside the secret. */
    keys: readonly string[]
}

// The keys duplicated between shared/posthog-django/common.yaml and
// apps/temporal-worker-data-warehouse/values.yaml in PostHog/charts.
export const PROVIDERS: Readonly<Record<string, ProviderDefinition>> = {
    'bing-ads': {
        keys: [
            'BING_ADS_CLIENT_ID',
            'BING_ADS_CLIENT_SECRET',
            'BING_ADS_CLIENT_ID_FALLBACK',
            'BING_ADS_CLIENT_SECRET_FALLBACK',
            'BING_ADS_DEVELOPER_TOKEN',
        ],
    },
    'google-ads': {
        keys: [
            'GOOGLE_ADS_APP_CLIENT_ID',
            'GOOGLE_ADS_APP_CLIENT_SECRET',
            'GOOGLE_ADS_DEVELOPER_TOKEN',
            'GOOGLE_ADS_SERVICE_ACCOUNT_CLIENT_EMAIL',
            'GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY',
            'GOOGLE_ADS_SERVICE_ACCOUNT_PRIVATE_KEY_ID',
            'GOOGLE_ADS_SERVICE_ACCOUNT_TOKEN_URI',
        ],
    },
    'google-analytics': {
        keys: ['GOOGLE_ANALYTICS_APP_CLIENT_ID', 'GOOGLE_ANALYTICS_APP_CLIENT_SECRET'],
    },
    'google-search-console': {
        keys: ['GOOGLE_SEARCH_CONSOLE_APP_CLIENT_ID', 'GOOGLE_SEARCH_CONSOLE_APP_CLIENT_SECRET'],
    },
    'google-sheets': {
        keys: [
            'GOOGLE_SHEETS_SERVICE_ACCOUNT_CLIENT_EMAIL',
            'GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY',
            'GOOGLE_SHEETS_SERVICE_ACCOUNT_PRIVATE_KEY_ID',
            'GOOGLE_SHEETS_SERVICE_ACCOUNT_TOKEN_URI',
        ],
    },
    hubspot: {
        keys: ['HUBSPOT_APP_CLIENT_ID', 'HUBSPOT_APP_CLIENT_SECRET'],
    },
    'linkedin-ads': {
        keys: ['LINKEDIN_APP_CLIENT_ID', 'LINKEDIN_APP_CLIENT_SECRET'],
    },
    'meta-ads': {
        keys: ['META_ADS_APP_CLIENT_ID', 'META_ADS_APP_CLIENT_SECRET'],
    },
    resend: {
        keys: ['RESEND_APP_CLIENT_ID', 'RESEND_APP_CLIENT_SECRET'],
    },
    salesforce: {
        keys: ['SALESFORCE_CONSUMER_KEY', 'SALESFORCE_CONSUMER_SECRET'],
    },
    stripe: {
        // Deliberately absent: STRIPE_SIGNING_SECRET, which authenticates requests arriving
        // at ee/partners/stripe/api/provisioning/ rather than requests we make, and
        // STRIPE_POSTHOG_OAUTH_CLIENT_ID, a public client id. Both stay as plain env vars.
        keys: ['STRIPE_APP_CLIENT_ID', 'STRIPE_APP_SECRET_KEY'],
    },
    'tiktok-ads': {
        keys: ['TIKTOK_ADS_CLIENT_ID', 'TIKTOK_ADS_CLIENT_SECRET'],
    },
    'youtube-analytics': {
        keys: ['YOUTUBE_ANALYTICS_APP_CLIENT_ID', 'YOUTUBE_ANALYTICS_APP_CLIENT_SECRET'],
    },
}

export const PROVIDER_NAMES: readonly string[] = Object.keys(PROVIDERS).sort()

// A key belongs to exactly one provider. Two providers claiming one would make "which
// secret do I rotate" ambiguous, so the manifest fails to load instead.
function buildKeyIndex(): ReadonlyMap<string, string> {
    const index = new Map<string, string>()
    for (const [provider, definition] of Object.entries(PROVIDERS)) {
        for (const key of definition.keys) {
            const existing = index.get(key)
            if (existing) {
                throw new Error(`Key ${key} is claimed by both ${existing} and ${provider} in the provider manifest`)
            }
            index.set(key, provider)
        }
    }
    return index
}

const KEY_TO_PROVIDER = buildKeyIndex()

/** The provider owning `key`, or null when the key is not in the manifest. */
export function providerForKey(key: string): string | null {
    return KEY_TO_PROVIDER.get(key) ?? null
}
