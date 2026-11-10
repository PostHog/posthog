import { describe, expect, it } from 'vitest'

import { providerSpec } from '@/providers'
import { displayName, dotGet, instanceBaseUrl } from '@/providers/paths'
import type { ProviderSpec, TokenSpec } from '@/providers/schema'

function spec(kind: string): ProviderSpec {
    const found = providerSpec(kind)
    if (!found) {
        throw new Error(`no spec for ${kind}`)
    }
    return found
}

describe('dotGet', () => {
    it.each<[string, unknown, string, unknown]>([
        ['walks a nested path', { team: { name: 'Acme' } }, 'team.name', 'Acme'],
        // Token info fields are stored under their dotted names, so the literal key must win.
        [
            'prefers a literal dotted key',
            { 'data.viewer.organization.id': 'org-1', data: { viewer: { organization: { id: 'other' } } } },
            'data.viewer.organization.id',
            'org-1',
        ],
        ['falls back to the walk when the literal key is null', { 'a.b': null, a: { b: 2 } }, 'a.b', 2],
        ['stops at a missing key', { team: {} }, 'team.name', undefined],
        ['stops at a non-object', { team: 'Acme' }, 'team.name', undefined],
        ['does not index into arrays', { list: ['x'] }, 'list.0', undefined],
    ])('%s', (_, value, path, expected) => {
        expect(dotGet(value, path)).toEqual(expected)
    })
})

describe('display name', () => {
    it.each<[string, string, Record<string, unknown>, string | null, string, string]>([
        ['the OAuth name path', 'slack', { team: { name: 'Acme' } }, 'T123', 'oauth', 'Acme'],
        ['the external id when the name is missing', 'slack', {}, 'T123', 'oauth', 'T123'],
        [
            'a literal dotted Linear key',
            'linear',
            { 'data.viewer.organization.name': 'Acme' },
            'org-1',
            'oauth',
            'Acme',
        ],
        ['the GitHub account', 'github', { account: { name: 'posthog' } }, '42', 'oauth', 'posthog'],
        ['the fixed text for a nameless key file row', 'google-cloud-storage', {}, null, 'credentials', 'unknown ID'],
        [
            'the external id of a key file row',
            'google-cloud-storage',
            {},
            'sa@example.iam.gserviceaccount.com',
            'credentials',
            'sa@example.iam.gserviceaccount.com',
        ],
        // A row on another auth type has another config shape, so it stores its own name.
        [
            'the stored name of a non-default auth type',
            'slack',
            { display_name: 'Bot', team: { name: 'Acme' } },
            'T1',
            'token',
            'Bot',
        ],
        [
            'the id of a non-default auth type with no stored name',
            'slack',
            { team: { name: 'Acme' } },
            'T1',
            'token',
            'ID: T1',
        ],
    ])('uses %s', (_, kind, config, externalId, authType, expected) => {
        expect(displayName(spec(kind), { config, externalId, authType })).toBe(expected)
    })
})

describe('instance base URL', () => {
    const token = spec('salesforce').token as TokenSpec

    it.each<[string, unknown, string | null]>([
        ['a production org', 'https://na1.salesforce.com', 'https://na1.salesforce.com'],
        [
            'a sandbox My Domain',
            'https://acme--dev.sandbox.my.salesforce.com/',
            'https://acme--dev.sandbox.my.salesforce.com',
        ],
        ['an upper-case host', 'https://ACME.my.salesforce.com', 'https://acme.my.salesforce.com'],
        // Each of these would send the shared client secret to a host that Salesforce does not own.
        ['plain http', 'http://na1.salesforce.com', null],
        ['another domain', 'https://attacker.example', null],
        ['a look-alike suffix', 'https://salesforce.com.attacker.example', null],
        ['the bare apex domain', 'https://salesforce.com', null],
        ['user info', 'https://user:pass@na1.salesforce.com', null],
        ['a user name that looks like the host', 'https://na1.salesforce.com@attacker.example', null],
        ['an explicit port', 'https://na1.salesforce.com:8443', null],
        ['the default port written out', 'https://na1.salesforce.com:443', null],
        ['a bad port', 'https://na1.salesforce.com:abc/', null],
        ['not a URL', 'na1.salesforce.com', null],
        ['not a string', 42, null],
        ['no value', undefined, null],
    ])('accepts or refuses %s', (_, instanceUrl, expected) => {
        expect(instanceBaseUrl(token, { instance_url: instanceUrl })).toBe(expected)
    })

    it('is null for a kind without an instance host rule', () => {
        expect(
            instanceBaseUrl(spec('hubspot').token as TokenSpec, { instance_url: 'https://na1.salesforce.com' })
        ).toBeNull()
    })
})
