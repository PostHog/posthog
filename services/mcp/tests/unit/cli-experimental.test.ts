import { describe, expect, it } from 'vitest'

import { EXPERIMENTAL_API_ENV, isExperimentalApiEnabled, requireExperimentalApiEnabled } from '@/cli/experimental'

describe('CLI experimental gate', () => {
    it('is disabled by default', () => {
        expect(isExperimentalApiEnabled({})).toBe(false)
    })

    it('accepts explicit enabled environment values', () => {
        for (const value of ['1', 'true', 'TRUE', 'yes', 'on']) {
            expect(isExperimentalApiEnabled({ [EXPERIMENTAL_API_ENV]: value })).toBe(true)
        }
    })

    it('rejects non-enabled environment values', () => {
        for (const value of ['0', 'false', 'no', '']) {
            expect(isExperimentalApiEnabled({ [EXPERIMENTAL_API_ENV]: value })).toBe(false)
        }
    })

    it('allows the per-command flag override', () => {
        expect(() => requireExperimentalApiEnabled({ flagEnabled: true, env: {} })).not.toThrow()
    })

    it('explains how to enable the command group', () => {
        expect(() => requireExperimentalApiEnabled({ env: {} })).toThrow(EXPERIMENTAL_API_ENV)
        expect(() => requireExperimentalApiEnabled({ env: {} })).toThrow('--experimental')
    })
})
