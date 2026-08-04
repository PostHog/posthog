import { describe, expect, it } from 'vitest'

import { createDevHonoChildEnv } from '../../scripts/dev-hono-env'

describe('createDevHonoChildEnv', () => {
    it.each([
        [{ API_URL: 'http://localhost:8000' }, 'development'],
        [{ API_URL: 'http://localhost:8000', NODE_ENV: 'production' }, 'production'],
    ])('sets the expected runtime environment for %o', (parentEnv, expectedNodeEnv) => {
        expect(createDevHonoChildEnv(parentEnv).NODE_ENV).toBe(expectedNodeEnv)
    })

    it('enables orchestration tool discovery by default', () => {
        expect(createDevHonoChildEnv({}).FEATURE_FLAG_OVERRIDES).toBe('{"tasks-orchestration":true}')
    })

    it('preserves explicit feature flag overrides', () => {
        const overrides = '{"tasks-orchestration":false,"another-flag":true}'
        expect(createDevHonoChildEnv({ FEATURE_FLAG_OVERRIDES: overrides }).FEATURE_FLAG_OVERRIDES).toBe(overrides)
    })
})
