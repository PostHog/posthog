import { describe, expect, it } from 'vitest'

import { createDevHonoChildEnv } from '../../scripts/dev-hono-env'

describe('createDevHonoChildEnv', () => {
    it.each([
        [{ API_URL: 'http://localhost:8000' }, 'development'],
        [{ API_URL: 'http://localhost:8000', NODE_ENV: 'production' }, 'production'],
    ])('sets the expected runtime environment for %o', (parentEnv, expectedNodeEnv) => {
        expect(createDevHonoChildEnv(parentEnv).NODE_ENV).toBe(expectedNodeEnv)
    })
})
