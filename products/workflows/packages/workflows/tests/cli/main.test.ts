import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { makeWorkspace, runCli } from './harness.js'

describe('main', () => {
    it('prints the usage on --help and exits 0', async () => {
        const result = await runCli(['--help'], { workspace: makeWorkspace() })

        assert.equal(result.code, 0)
        assert.equal(result.stderr, '')
        assert.match(result.stdout, /^posthog-workflows <command> <file> \[options\]$/m)
        assert.match(result.stdout, /^ {2}--project <id> {3}the project to compare against or push to\./m)
        assert.match(result.stdout, /^ {2}--host <url> {5}the PostHog instance\./m)
    })

    it('refuses an option without its value, naming the option', async () => {
        const result = await runCli(['check', 'flows/onboarding.ts', '--project'], { workspace: makeWorkspace() })

        assert.equal(result.code, 1)
        assert.match(result.stderr, /^status: missing_option_value$/m)
        assert.match(result.stderr, /^message: --project needs a value\.$/m)
    })

    it('refuses a project value that is not ASCII decimal digits', async () => {
        for (const project of ['abc', '１２']) {
            const result = await runCli(['check', 'flows/onboarding.ts', '--project', project], {
                workspace: makeWorkspace(),
            })

            assert.equal(result.code, 1)
            assert.match(result.stderr, /^status: invalid_project$/m)
            assert.match(result.stderr, /must be an ASCII decimal number/)
        }
    })
})
