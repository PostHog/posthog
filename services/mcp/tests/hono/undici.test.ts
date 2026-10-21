import { spawnSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'

describe('Hono HTTP runtime', () => {
    it('reads a response after socket EOF while the body has backpressure', () => {
        const result = spawnSync(
            process.execPath,
            [
                '--import',
                'tsx',
                '--import',
                fileURLToPath(new URL('../../src/hono/undici.ts', import.meta.url)),
                fileURLToPath(new URL('./fixtures/undici-backpressure.mjs', import.meta.url)),
            ],
            { cwd: fileURLToPath(new URL('../..', import.meta.url)), encoding: 'utf8', timeout: 10000 }
        )

        expect(result.error).toBeUndefined()
        expect(result.stderr).toBe('')
        expect(result.status).toBe(0)
        expect(result.stdout.trim()).toBe('response complete')
    })
})
