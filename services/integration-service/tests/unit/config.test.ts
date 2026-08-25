import { afterEach, describe, expect, it } from 'vitest'

import { loadConfig } from '@/lib/config'

const VAR = 'INTEGRATION_SERVICE_RELOAD_SECONDS'

describe('loadConfig integers', () => {
    afterEach(() => {
        delete process.env[VAR]
    })

    it.each([
        ['unset falls back to the default', undefined, 30],
        ['a valid value parses', '45', 45],
    ])('%s', (_label, value, expected) => {
        if (value !== undefined) {
            process.env[VAR] = value
        }
        expect(loadConfig().reloadSeconds).toBe(expected)
    })

    // Boot is fail-fast everywhere else; a malformed number must not silently run a
    // cadence the operator did not set.
    it('throws on a malformed value instead of silently defaulting', () => {
        process.env[VAR] = 'not-a-number'
        expect(() => loadConfig()).toThrow(VAR)
    })
})

describe('loadConfig production guards', () => {
    const PROD_VARS = ['NODE_ENV', 'INTEGRATION_SERVICE_ENV', 'INTEGRATION_SERVICE_DATABASE_URL']

    afterEach(() => {
        for (const key of PROD_VARS) {
            delete process.env[key]
        }
    })

    function setProduction(): void {
        process.env.NODE_ENV = 'production'
        process.env.INTEGRATION_SERVICE_ENV = 'prod-us'
        process.env.INTEGRATION_SERVICE_DATABASE_URL = 'postgres://usage:usage@localhost:5432/usage'
    }

    it.each([['INTEGRATION_SERVICE_ENV'], ['INTEGRATION_SERVICE_DATABASE_URL']])(
        'refuses to boot in production without %s',
        (missing) => {
            setProduction()
            delete process.env[missing]

            expect(() => loadConfig()).toThrow(missing)
        }
    )

    it('boots in production once every required variable is set', () => {
        setProduction()
        expect(loadConfig().env).toBe('prod-us')
    })
})
