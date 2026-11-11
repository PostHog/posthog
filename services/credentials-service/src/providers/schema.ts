// The provider spec ("the DSL"): one object per integration kind, which says how the service talks
// to that kind's provider. It is a port of `OauthConfig`, `client_credentials_for_kind`, the
// fallback clients and `refresh_tracking.py` in `posthog/models/integration/`.
//
// Specs are plain data. Files that only need the types import them with `import type`, so the
// catalogue bundle carries no zod and builds without node_modules (see `src/catalogue.ts`).

import { z } from 'zod'

import { AUTHORIZE_PLACEHOLDERS } from './authorize'
import { applyOverrides, type SpecContext } from './overrides'

export const AUTH_TYPES = ['oauth', 'token', 'credentials'] as const

const KIND = /^[a-z0-9][a-z0-9_-]{0,63}$/
// A platform-secret name on the mount. `__` names are caller signing keys, which the mount never serves.
const SECRET_KEY = /^(?!__)[A-Z][A-Z0-9_]*$/
const PLACEHOLDER = /\{([a-z_]+)\}/g
const HTTPS_URL = /^https:\/\/[^\s/?#]+[^\s#]*$/

// A secret that only the provider registry reads. The secrets route never serves this prefix.
const PROVIDER_SECRET_KEY = /^__PROVIDER_[A-Z][A-Z0-9_]*$/

const kindName = z.string().regex(KIND, 'must be a lowercase kind name')
const secretKey = z.string().regex(SECRET_KEY, 'must be an uppercase platform-secret name')
const providerSecretKey = z.string().regex(PROVIDER_SECRET_KEY, 'must be a `__PROVIDER_` platform-secret name')
const httpsUrl = z.string().regex(HTTPS_URL, 'must be an https URL')
// A dot path into a JSON object, read like `common.dot_get`: a literal key with dots wins over traversal.
const jsonPath = z.string().min(1)

const authorizeParam = z.tuple([z.string().min(1), z.string()])

const authorizeSchema = z.strictObject({
    /** May hold `{name}` placeholders, each named in `urlValues`. */
    url: z.string().min(1),
    /** Space-separated for most providers. Slack takes commas. */
    scope: z.string(),
    /**
     * The whole ordered parameter list, for a provider that does not take the standard OAuth set
     * (a GitHub App install). Without it, the standard set comes from `standardAuthorizeParams`.
     */
    params: z.array(authorizeParam).min(1).optional(),
    /** Added after the standard parameters, in this order. Not allowed with `params`. */
    extraParams: z.array(authorizeParam).optional(),
    /** RFC 7636 with S256. Django keeps the verifier; the service gets it at the code exchange. */
    pkce: z.boolean(),
    /** Hex-encode the state, for a provider that changes the state before it sends it back. */
    opaqueState: z.boolean(),
    /** Platform settings that fill the URL placeholders, by placeholder name. */
    urlValues: z.record(z.string().regex(/^[a-z_]+$/), secretKey).optional(),
})

const tokenSchema = z.strictObject({
    url: httpsUrl,
    revokeUrl: httpsUrl.optional(),
    /**
     * How the client authenticates at the token endpoint.
     * - `client_secret_post`: id and secret in the form body (the default of `OauthIntegration`).
     * - `client_secret_basic`: HTTP Basic with id and secret (Reddit, Pinterest).
     * - `secret_basic`: HTTP Basic with the secret as the user name and no id (Stripe Apps).
     * - `json_app_id`: a JSON body with `app_id` and `secret` (TikTok Business).
     */
    auth: z.enum(['client_secret_post', 'client_secret_basic', 'secret_basic', 'json_app_id']),
    /** Token URLs to try in order when the code exchange at `url` fails (the Salesforce sandbox host). */
    exchangeFallbackUrls: z.array(httpsUrl).optional(),
    /**
     * Refresh and revoke at the host that a config field names, only when the host passes the check.
     * Otherwise the service uses `url` and `revokeUrl`. A config write then cannot send the client
     * secret to another origin. The service enforces this on every exchange and refresh.
     */
    tokenHost: z
        .strictObject({
            fromConfig: z.string().min(1),
            /** The host must end with one of these, for example `.salesforce.com`. The value must be a plain https URL with no port. */
            allow: z.array(z.string().regex(/^\.[a-z0-9.-]+$/)).min(1),
            tokenPath: z.string().startsWith('/'),
            revokePath: z.string().startsWith('/'),
        })
        .optional(),
})

const clientSecretKeysSchema = z.strictObject({
    clientId: providerSecretKey,
    clientSecret: providerSecretKey,
    /**
     * Credentials of a rotated or migrated app, tried in order after the primary pair fails, so
     * grants that only the old app can refresh keep working until the user reconnects. A fallback
     * is used only when its secret is set. A fallback without its own id uses the primary id.
     */
    fallbacks: z
        .array(z.strictObject({ clientId: providerSecretKey.optional(), clientSecret: providerSecretKey }))
        .optional(),
})

const tokenInfoSchema = z.strictObject({
    /** Where the external id comes from, after `configFields` are merged into the token response. */
    idPath: jsonPath,
    namePath: jsonPath,
    /** A call that identifies the account. Without it, the paths read the token response itself. */
    request: z
        .strictObject({
            /** May hold `:access_token`, which the service replaces with the token (HubSpot). */
            url: httpsUrl,
            /** Send this GraphQL query as a POST. Without it, the request is a GET. */
            graphqlQuery: z.string().min(1).optional(),
            /** Copied from the response into config, each under its own path as the key. */
            configFields: z.array(jsonPath),
        })
        .optional(),
})

const errorMatcherSchema = z.strictObject({
    /** A dot path into the JSON error body. */
    path: jsonPath,
    equals: z.union([z.string(), z.number()]),
    /** Match only this HTTP status. */
    status: z.number().int().optional(),
    /** Match only a status below this one. */
    statusBelow: z.number().int().optional(),
})

const refreshSchema = z.strictObject({
    /**
     * What the provider does with a refresh token after use. Every mode stores a refresh token
     * that a response returns.
     * - `static`: the token stays valid, so a retry after a lost response is safe.
     * - `rotating`: the provider can issue a new token and end the old one. Refresh under a row lock.
     * - `single_use`: the token ends at first use. Refresh under `FOR UPDATE` and never retry a used token.
     */
    mode: z.enum(['rotating', 'static', 'single_use']),
    /** Refresh when this part of the token lifetime has passed. 0.5 is the half-life of `access_token_expired`. */
    refreshAtLifetimeFraction: z.number().gt(0).lt(1),
    /** The lifetime to assume when the provider sends no `expires_in`. */
    defaultExpiresInSeconds: z.number().int().positive().optional(),
    backoff: z.strictObject({
        baseSeconds: z.number().int().positive(),
        maxSeconds: z.number().int().positive(),
    }),
    /** This many `invalid_grant` failures in a row make the row terminal. */
    terminalAfter: z.number().int().positive(),
    /**
     * Provider-specific bodies that also mean `invalid_grant`. The OAuth `invalid_grant` code
     * always does, so it is not listed here.
     */
    terminalErrors: z.array(errorMatcherSchema),
})

const mintSchema = z.discriminatedUnion('type', [
    z.strictObject({
        type: z.literal('github_installation_token'),
        /** GitHub accepts the App client id as the JWT issuer. */
        appIdKey: providerSecretKey,
        privateKeyKey: providerSecretKey,
        installationIdField: z.string().min(1),
    }),
    z.strictObject({
        type: z.literal('google_sa_jwt'),
        scope: httpsUrl,
        /** The secret field that holds the service account key file. */
        keyField: z.string().min(1),
        /** The key file names its token endpoint, so a hand-edited key file could send the grant anywhere. */
        tokenUriAllowlist: z.array(httpsUrl).min(1),
    }),
    z.strictObject({ type: z.literal('apns_jwt') }),
    z.strictObject({ type: z.literal('fcm') }),
])

const overrideSchema = z.strictObject({
    authorize: authorizeSchema.partial().optional(),
    token: tokenSchema.partial().optional(),
    clientSecretKeys: clientSecretKeysSchema.optional(),
    tokenInfo: tokenInfoSchema.partial().optional(),
})

export const providerSpecSchema = z
    .strictObject({
        kind: kindName,
        /** The kind's name in the UI, as `KindSpec.label`. */
        label: z.string().min(1),
        authTypes: z.strictObject({
            /** Stored data: a row keeps `config.auth_type` only when it is not this. */
            default: z.enum(AUTH_TYPES),
            others: z.array(z.enum(AUTH_TYPES)),
        }),
        /** The browser leg. Django builds this URL from the generated catalogue. */
        authorize: authorizeSchema.optional(),
        token: tokenSchema.optional(),
        clientSecretKeys: clientSecretKeysSchema.optional(),
        tokenInfo: tokenInfoSchema.optional(),
        /** Partial replacements, by service environment (`dev`, `prod-us`, ...) or by the row's region. */
        overrides: z
            .strictObject({
                environment: z.record(z.string().min(1), overrideSchema).optional(),
                region: z.record(z.string().min(1), overrideSchema).optional(),
            })
            .optional(),
        /**
         * Config keys that name the account, installation or region of the row. They are set at
         * create and exchange only, and `PATCH` refuses them, because the AAD does not cover them.
         */
        identityConfigKeys: z.array(z.string().min(1)),
        /**
         * Rules for the row's region, by region. A region listed here exists only in the service
         * environments in `allowedIn`, for example a DEV region that production must refuse.
         */
        regions: z
            .record(z.string().min(1), z.strictObject({ allowedIn: z.array(z.string().min(1)).min(1) }))
            .optional(),
        refresh: refreshSchema.optional(),
        mint: mintSchema.optional(),
        /** The secret fields that `/resolve` returns. Never a refresh token. */
        resolveExposes: z
            .array(z.string().min(1))
            .min(1)
            .refine((fields) => !fields.includes('refresh_token'), 'must not expose the refresh token'),
        /** The row's name in the UI: the first config path with a value, else the external id. */
        displayName: z.strictObject({
            configPaths: z.array(jsonPath),
            /** Used instead of the external id when the row has none. */
            whenMissing: z.string().optional(),
        }),
    })
    .superRefine((spec, ctx) => {
        const issue = (message: string, path: (string | number)[]): void => {
            ctx.addIssue({ code: 'custom', message, path })
        }
        if (spec.authTypes.others.includes(spec.authTypes.default)) {
            issue('lists the default auth type again', ['authTypes', 'others'])
        }
        const usesOauth = spec.authTypes.default === 'oauth' || spec.authTypes.others.includes('oauth')
        if (usesOauth !== Boolean(spec.authorize)) {
            issue('an oauth kind needs `authorize`, and only an oauth kind may have it', ['authorize'])
        }
        if (spec.token && !spec.clientSecretKeys) {
            issue('a token endpoint needs `clientSecretKeys`', ['clientSecretKeys'])
        }
        if (spec.token && !spec.tokenInfo) {
            issue('a code exchange needs `tokenInfo` to find the external id', ['tokenInfo'])
        }
        for (const context of [{}, ...overrideContexts(spec)]) {
            const tokenHost = applyOverrides(spec, context).token?.tokenHost
            if (tokenHost && !spec.identityConfigKeys.includes(tokenHost.fromConfig)) {
                const where = Object.keys(context).length ? `override ${JSON.stringify(context)}: ` : ''
                issue(`${where}the config field behind \`tokenHost\` must be an identity config key`, [
                    'identityConfigKeys',
                ])
            }
        }
        const keyField = spec.mint && 'keyField' in spec.mint ? spec.mint.keyField : undefined
        if (
            keyField &&
            spec.resolveExposes.some(
                (field) => field === keyField || keyField.startsWith(`${field}.`) || field.startsWith(`${keyField}.`)
            )
        ) {
            issue('must not expose the key that the minter signs with', ['resolveExposes'])
        }
        if (spec.refresh && !spec.token && !spec.mint) {
            issue('refresh needs a token endpoint or a minter', ['refresh'])
        }
        if (spec.refresh && spec.refresh.backoff.maxSeconds < spec.refresh.backoff.baseSeconds) {
            issue('backoff max is below its base', ['refresh', 'backoff'])
        }
        if (spec.authorize) {
            checkAuthorize(spec.authorize, issue)
            // Overrides merge into the base, so check every authorize block a context can produce.
            for (const context of overrideContexts(spec)) {
                const merged = applyOverrides(spec, context).authorize
                if (merged) {
                    const where = `override ${JSON.stringify(context)}`
                    checkAuthorize(merged, (message, path) => issue(`${where}: ${message}`, ['overrides', ...path]))
                }
            }
        }
    })

function overrideContexts(spec: ProviderSpec): SpecContext[] {
    const environments = Object.keys(spec.overrides?.environment ?? {})
    const regions = Object.keys(spec.overrides?.region ?? {})
    return [
        ...environments.map((environment) => ({ environment })),
        ...regions.map((region) => ({ region })),
        ...environments.flatMap((environment) => regions.map((region) => ({ environment, region }))),
    ]
}

function checkAuthorize(
    authorize: z.infer<typeof authorizeSchema>,
    issue: (message: string, path: (string | number)[]) => void
): void {
    if (authorize.params && authorize.extraParams) {
        issue('`params` replaces the standard set, so it cannot have `extraParams` too', ['authorize'])
    }
    const urlNames = [...authorize.url.matchAll(PLACEHOLDER)].map((match) => match[1])
    const declared = Object.keys(authorize.urlValues ?? {})
    if (urlNames.sort().join() !== declared.sort().join()) {
        issue('URL placeholders and `urlValues` must name the same values', ['authorize', 'urlValues'])
    }
    if (!HTTPS_URL.test(authorize.url.replace(PLACEHOLDER, 'x'))) {
        issue('must be an https URL', ['authorize', 'url'])
    }
    const values = [...(authorize.params ?? []), ...(authorize.extraParams ?? [])].map(([, value]) => value)
    for (const value of values) {
        if (value.startsWith('{') && !(AUTHORIZE_PLACEHOLDERS as readonly string[]).includes(value)) {
            issue(`unknown placeholder ${value}`, ['authorize'])
        }
    }
    if (authorize.params) {
        // The state carries the CSRF token, so a custom parameter list must still send it.
        if (!values.includes('{state}')) {
            issue('custom `params` must send `{state}`', ['authorize', 'params'])
        }
        if (authorize.pkce && !values.includes('{code_challenge}')) {
            issue('a PKCE kind with custom `params` must send `{code_challenge}`', ['authorize', 'params'])
        }
    }
}

export type AuthType = (typeof AUTH_TYPES)[number]
export type ProviderSpec = z.infer<typeof providerSpecSchema>
export type AuthorizeSpec = z.infer<typeof authorizeSchema>
export type TokenSpec = z.infer<typeof tokenSchema>
export type ClientSecretKeys = z.infer<typeof clientSecretKeysSchema>
export type TokenInfoSpec = z.infer<typeof tokenInfoSchema>
export type RefreshSpec = z.infer<typeof refreshSchema>
export type ErrorMatcher = z.infer<typeof errorMatcherSchema>
export type MintSpec = z.infer<typeof mintSchema>
export type ProviderOverride = z.infer<typeof overrideSchema>
