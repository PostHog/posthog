import { describe, expect, it } from 'vitest'

import { PROVIDER_SPECS, providerSpec } from '@/providers'
import { buildAuthorizeUrl, pkceChallenge, pythonUrlencode } from '@/providers/authorize'
import { applyOverrides } from '@/providers/overrides'
import type { AuthorizeSpec, ProviderSpec } from '@/providers/schema'

// The expected URLs come from `OauthIntegration.authorize_url` (posthog/models/integration/oauth.py)
// and `github_app_install_url` (posthog/api/github_callback/types.py), run through Python's
// `urlencode` with these inputs. A change here means Django's URL and the catalogue differ.
const STATE = 'next=%2Finsights%3Ftab%3D1&token=state-token&team_id=2'
const ENCODED_STATE = 'next%3D%252Finsights%253Ftab%253D1%26token%3Dstate-token%26team_id%3D2'
// The verifier and challenge of RFC 7636, appendix B.
const VERIFIER = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
const CHALLENGE = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'

const SLACK_SCOPES =
    'app_mentions%3Aread%2Cassistant%3Awrite%2Ccanvases%3Awrite%2Cchannels%3Ahistory%2Cchannels%3Amanage%2Cchannels%3Aread%2Cchat%3Awrite%2Cchat%3Awrite.customize%2Ccommands%2Cfiles%3Aread%2Cfiles%3Awrite%2Cgroups%3Ahistory%2Cgroups%3Aread%2Cim%3Ahistory%2Clinks%3Aread%2Clinks%3Awrite%2Cmpim%3Ahistory%2Cmpim%3Aread%2Creactions%3Aread%2Creactions%3Awrite%2Cteam%3Aread%2Cusers%3Aread%2Cusers%3Aread.email'

function redirect(kind: string): string {
    return `redirect_uri=https%3A%2F%2Fus.posthog.com%2Fintegrations%2F${kind}%2Fcallback`
}

function standard(kind: string, scope: string): string {
    return `client_id=test-client-id&scope=${scope}&${redirect(kind)}&response_type=code&state=${ENCODED_STATE}`
}

const GOLDEN: Record<string, string> = {
    slack: `https://slack.com/oauth/v2/authorize?${standard('slack', SLACK_SCOPES)}`,
    salesforce: `https://login.salesforce.com/services/oauth2/authorize?${standard('salesforce', 'full+refresh_token')}&code_challenge=${CHALLENGE}&code_challenge_method=S256`,
    hubspot: `https://app.hubspot.com/oauth/authorize?${standard(
        'hubspot',
        'tickets+crm.objects.contacts.write+sales-email-read+crm.objects.companies.read+crm.objects.deals.read+crm.objects.contacts.read+crm.objects.quotes.read+crm.objects.companies.write'
    )}&optional_scope=analytics.behavioral_events.send+behavioral_events.event_definitions.read_write+crm.objects.leads.read+crm.objects.owners.read+crm.objects.line_items.read+crm.objects.products.read+crm.objects.invoices.read+crm.objects.orders.read+crm.objects.subscriptions.read+crm.objects.commercepayments.read+crm.objects.forecasts.read+conversations.read`,
    'google-ads': `https://accounts.google.com/o/oauth2/v2/auth?${standard(
        'google-ads',
        'https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fadwords+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email'
    )}&access_type=offline&prompt=consent`,
    'google-sheets': `https://accounts.google.com/o/oauth2/v2/auth?${standard(
        'google-sheets',
        'https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fspreadsheets+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email'
    )}&access_type=offline&prompt=consent`,
    linear: `https://linear.app/oauth/authorize?${standard('linear', 'read+issues%3Acreate')}&actor=application&prompt=consent`,
    // The install flow puts no team id in the state.
    github: 'https://github.com/apps/posthog-test/installations/new?state=next%3D%252Finsights%253Ftab%253D1%26token%3Dstate-token',
}

function authorizeOf(spec: ProviderSpec | undefined): AuthorizeSpec {
    if (!spec?.authorize) {
        throw new Error('expected an authorize block')
    }
    return spec.authorize
}

function build(kind: string, spec: ProviderSpec | undefined = providerSpec(kind)): string {
    const authorize = authorizeOf(spec)
    return buildAuthorizeUrl(authorize, {
        clientId: 'test-client-id',
        redirectUri: `https://us.posthog.com/integrations/${kind}/callback`,
        state: kind === 'github' ? 'next=%2Finsights%3Ftab%3D1&token=state-token' : STATE,
        ...(authorize.pkce ? { codeChallenge: pkceChallenge(VERIFIER) } : {}),
        urlValues: { app_slug: 'posthog-test' },
    })
}

describe('authorize URL', () => {
    it.each(Object.entries(GOLDEN))('matches what Django builds for %s', (kind, expected) => {
        expect(build(kind)).toBe(expected)
    })

    it('has a golden URL for every kind with an authorize leg', () => {
        const withAuthorize = PROVIDER_SPECS.filter((spec) => spec.authorize).map((spec) => spec.kind)
        expect(Object.keys(GOLDEN).sort()).toEqual(withAuthorize.sort())
    })

    it('asks for the in-review Slack scopes only in dev', () => {
        const dev = applyOverrides(providerSpec('slack') as ProviderSpec, { environment: 'dev' })
        expect(build('slack', dev)).toBe(
            `https://slack.com/oauth/v2/authorize?${standard('slack', `${SLACK_SCOPES}%2Ccanvases%3Aread%2Cchannels%3Ajoin`)}`
        )
        const prod = applyOverrides(providerSpec('slack') as ProviderSpec, { environment: 'prod-us' })
        expect(build('slack', prod)).toBe(GOLDEN['slack'])
    })

    // Help Scout drops everything after the first `&` of a state it gets back, so the state goes hex.
    it('hex-encodes an opaque state', () => {
        const authorize: AuthorizeSpec = {
            url: 'https://example.com/authorize',
            scope: '',
            pkce: false,
            opaqueState: true,
        }
        const url = new URL(buildAuthorizeUrl(authorize, { clientId: 'id', redirectUri: 'https://r', state: STATE }))
        expect(url.searchParams.get('state')).toBe(
            '6e6578743d253246696e7369676874732533467461622533443126746f6b656e3d73746174652d746f6b656e267465616d5f69643d32'
        )
    })

    it.each([
        ['a PKCE kind without a code challenge', 'salesforce', {}, /code challenge/],
        ['an install URL without its slug', 'github', { urlValues: {} }, /app_slug/],
    ])('refuses %s', (_, kind, input, error) => {
        const authorize = authorizeOf(providerSpec(kind))
        expect(() =>
            buildAuthorizeUrl(authorize, { clientId: 'id', redirectUri: 'https://r', state: STATE, ...input })
        ).toThrow(error)
    })

    it('computes the RFC 7636 S256 challenge', () => {
        expect(pkceChallenge(VERIFIER)).toBe(CHALLENGE)
    })

    // Python keeps `~` and encodes `*'()!`, where encodeURIComponent and URLSearchParams do not.
    it('encodes like Python urlencode', () => {
        expect(pythonUrlencode([['a b', "x~y*z'(1)!/é+&="]])).toBe('a+b=x~y%2Az%27%281%29%21%2F%C3%A9%2B%26%3D')
    })
})
