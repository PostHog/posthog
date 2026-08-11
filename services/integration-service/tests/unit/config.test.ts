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

// The guard is what keeps /metrics bearer-gated in production. The resolve counter maps
// which deployment reads which credential, so an ungated scrape has to be impossible by
// accident rather than by review.
describe('loadConfig production guards', () => {
    const PROD_VARS = ['NODE_ENV', 'INTEGRATION_SERVICE_ENV', 'INTEGRATION_SERVICE_METRICS_TOKEN']

    afterEach(() => {
        for (const key of PROD_VARS) {
            delete process.env[key]
        }
    })

    function setProduction(): void {
        process.env.NODE_ENV = 'production'
        process.env.INTEGRATION_SERVICE_ENV = 'prod-us'
        process.env.INTEGRATION_SERVICE_METRICS_TOKEN = 'scrape-token'
    }

    it.each([['INTEGRATION_SERVICE_ENV'], ['INTEGRATION_SERVICE_METRICS_TOKEN']])(
        'refuses to boot in production without %s',
        (missing) => {
            setProduction()
            delete process.env[missing]

            expect(() => loadConfig()).toThrow(missing)
        }
    )

    it('boots in production once every required variable is set', () => {
        setProduction()
        expect(loadConfig().metricsToken).toBe('scrape-token')
    })
})
