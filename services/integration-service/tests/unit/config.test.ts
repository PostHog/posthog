import { afterEach, describe, expect, it } from 'vitest'

import { loadConfig } from '@/lib/config.js'

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
