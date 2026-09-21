import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, it } from 'node:test'

import { makeWorkspace, runCli } from './harness.js'

describe('init', () => {
    it('writes a starter file whose key comes from the file name', async () => {
        const workspace = makeWorkspace()

        const result = await runCli(['init', 'flows/onboarding-nudge.ts'], { workspace })

        assert.equal(result.code, 0)
        assert.equal(
            result.stdout,
            [
                'Wrote flows/onboarding-nudge.ts with the key "onboarding-nudge".',
                'Next: edit the steps, then run posthog-workflows check flows/onboarding-nudge.ts',
                '',
            ].join('\n')
        )
        const written = readFileSync(join(workspace.dir, 'flows', 'onboarding-nudge.ts'), 'utf8')
        assert.match(written, /key: 'onboarding-nudge'/)
        assert.match(written, /export const onboardingNudge = workflow\(\{/)
    })

    it('writes a file the CLI then loads', async () => {
        const workspace = makeWorkspace()
        await runCli(['init', 'flows/onboarding.ts'], { workspace })

        const result = await runCli(['check', 'flows/onboarding.ts'], { workspace })

        assert.equal(result.code, 0)
        assert.match(result.stdout, /^ {4}key {6}onboarding$/m)
        assert.match(result.stdout, /^1 workflow\(s\), all valid\.$/m)
    })

    it('refuses to overwrite a file that is already there', async () => {
        const workspace = makeWorkspace({ 'flows/onboarding.ts': '// mine\n' })

        const result = await runCli(['init', 'flows/onboarding.ts'], { workspace })

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: file_exists$/m)
        assert.equal(readFileSync(join(workspace.dir, 'flows', 'onboarding.ts'), 'utf8'), '// mine\n')
    })
})
