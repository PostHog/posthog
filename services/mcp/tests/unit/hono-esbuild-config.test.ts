import { afterEach, describe, expect, it, vi } from 'vitest'

import { honoEsbuildOptions } from '../../scripts/hono-esbuild-config'

describe('honoEsbuildOptions', () => {
    afterEach(() => {
        vi.unstubAllEnvs()
    })

    // `$mcp_server_build` reads this define. Without it every production event
    // reports `dev`, which the analytics test's fallback assertion would not notice.
    it('stamps the commit the bundle was built from into the bundle', () => {
        vi.stubEnv('COMMIT_HASH', 'b3b941584bae0123')

        expect(honoEsbuildOptions().define?.['process.env.MCP_BUILD_SHA']).toBe('"b3b941584bae0123"')
    })

    it('defines an empty string, not undefined, when no commit is known', () => {
        vi.stubEnv('COMMIT_HASH', '')
        vi.stubEnv('MCP_BUILD_SHA', '')

        expect(honoEsbuildOptions().define?.['process.env.MCP_BUILD_SHA']).toBe('""')
    })
})
