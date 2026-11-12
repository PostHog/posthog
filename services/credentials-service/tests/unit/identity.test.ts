import { describe, expect, it } from 'vitest'

import { assertIdentityUnchanged } from '@/integrations/identity'

describe('assertIdentityUnchanged', () => {
    it.each([
        ['gitlab', { hostname: 'gitlab.example.com' }, { hostname: 'attacker.example.net' }],
        ['gitlab', { hostname: 'gitlab.example.com' }, {}],
        ['gitlab', {}, { hostname: 'attacker.example.net' }],
        ['slack', { installation_id: 'a' }, { installation_id: 'b' }],
        ['hubspot', { region: 'us' }, { region: 'eu' }],
    ])('refuses to change an identity key of %s', (kind, current, next) => {
        expect(() => assertIdentityUnchanged(kind, current, next)).toThrow(/identify the account/)
    })

    it.each([
        ['gitlab', { hostname: 'gitlab.example.com', note: 'a' }, { hostname: 'gitlab.example.com', note: 'b' }],
        ['hubspot', { hostname: 'a' }, { hostname: 'b' }],
        ['constructor', { x: 1 }, { x: 2 }],
    ])('allows other keys of %s to change', (kind, current, next) => {
        expect(() => assertIdentityUnchanged(kind, current, next)).not.toThrow()
    })
})
