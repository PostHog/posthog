// The provider manifest: which integration apps exist, and which credential fields
// each one holds.
//
// Deliberately code rather than discovered by listing Secrets Manager. Three reasons:
// the service needs no ListSecrets permission; a mistyped key name fails as an explicit
// "unknown key" instead of silently resolving to nothing; and the manifest is a
// reviewable, versioned statement of which integration apps PostHog owns and what
// credential material each one holds.
//
// One AWS secret per provider (`<prefix><provider>`), holding that provider's fields
// as a flat JSON object. Per-provider granularity matters because AWS staging labels
// apply to a whole secret version — rotating Stripe must not disturb Google.
//
// Key names are the existing Django env var names, unchanged. That makes the cutover
// a 1:1 mapping with nothing to get wrong. Logical `provider/field` names come later,
// when the per-team Integration model moves onto this service and there is a reason
// to rename.

export interface ProviderDefinition {
    /** Credential field names, i.e. the keys inside this provider's AWS secret. */
    keys: readonly string[]
}

// Phase 1: the platform credentials the data warehouse sources need. These are exactly
// the keys duplicated today between shared/posthog-django/common.yaml and
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
        keys: [
            'STRIPE_APP_CLIENT_ID',
            'STRIPE_APP_SECRET_KEY',
            'STRIPE_POSTHOG_OAUTH_CLIENT_ID',
            'STRIPE_SIGNING_SECRET',
        ],
    },
    'tiktok-ads': {
        keys: ['TIKTOK_ADS_CLIENT_ID', 'TIKTOK_ADS_CLIENT_SECRET'],
    },
    'youtube-analytics': {
        keys: ['YOUTUBE_ANALYTICS_APP_CLIENT_ID', 'YOUTUBE_ANALYTICS_APP_CLIENT_SECRET'],
    },
}

export const PROVIDER_NAMES: readonly string[] = Object.keys(PROVIDERS).sort()

// Reverse index, built once. A key belongs to exactly one provider; buildKeyIndex
// throws if the manifest ever violates that, since two providers claiming a key would
// make "which secret do I rotate" ambiguous.
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
