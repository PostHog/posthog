import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import { makeWorkspace, runCli, startStandIn, workflowFile } from './harness.js'

describe('check', () => {
    it('validates offline, names the half that ran, and exits 0 with no credentials', async () => {
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile({ secret: true }) })

        const result = await runCli(['check', 'flows/onboarding.ts'], {
            workspace,
            env: { CRM_WEBHOOK_SECRET: 'never-printed' },
        })

        assert.equal(result.code, 0)
        assert.equal(
            result.stdout,
            [
                'flows/onboarding.ts',
                '  onboarding -> "Onboarding nudge"',
                '    key      onboarding-nudge',
                '    status   draft',
                '    steps    4 (trigger, function, delay, exit)',
                '    secret   tell_the_crm.signing_secret from $CRM_WEBHOOK_SECRET, sent on every push',
                '    source   not detected: this version will not name a commit',
                '             fix: Run push from a git checkout, or from GitHub Actions or GitLab CI, so the version names the commit it came from.',
                '    diff     not compared',
                '1 workflow(s), all valid.',
                'diff skipped: no PostHog credentials in this environment, so the file was validated offline.',
                'Set POSTHOG_CLI_API_KEY and POSTHOG_CLI_PROJECT_ID to compare against a project.',
                '',
            ].join('\n')
        )
    })

    it('passes offline even when a secret the file names is not set', async () => {
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile({ secret: true }) })

        const result = await runCli(['check', 'flows/onboarding.ts'], { workspace })

        assert.equal(result.code, 0)
        assert.match(result.stdout, /^1 workflow\(s\), all valid\.$/m)
    })

    it('names what a push would change, and writes nothing', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        standIn.seed({ key: 'onboarding-nudge', name: 'Onboarding nudge', status: 'active' })
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await runCli(['check', 'flows/onboarding.ts'], {
            workspace,
            env: {
                POSTHOG_CLI_API_KEY: 'phx_test',
                POSTHOG_CLI_PROJECT_ID: '2',
                POSTHOG_CLI_HOST: standIn.url,
            },
        })

        assert.equal(result.code, 0)
        assert.match(result.stdout, /^ {4}result {3}would update$/m)
        assert.match(result.stdout, /^ {13}~ status: active -> draft$/m)
        assert.match(result.stdout, /^1 workflow\(s\): 0 would be created, 1 would be updated, 0 unchanged\.$/m)
        assert.match(
            result.stdout,
            /compared against project 2 on http:\/\/127\.0\.0\.1:\d+ \(credentials from the environment\)\.$/m
        )
        assert.deepEqual(
            standIn.requests.map((request) => request.method),
            ['GET']
        )
    })

    it('reports a workflow PostHog does not have yet as one it would create', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        const result = await runCli(['check', 'flows/onboarding.ts'], {
            workspace,
            env: { POSTHOG_CLI_API_KEY: 'phx_test', POSTHOG_CLI_PROJECT_ID: '2', POSTHOG_CLI_HOST: standIn.url },
        })

        assert.equal(result.code, 0)
        assert.match(result.stdout, /^ {4}result {3}would create$/m)
    })

    it('sends the version of the package as its user agent', async (t) => {
        const standIn = await startStandIn()
        t.after(() => standIn.close())
        const workspace = makeWorkspace({ 'flows/onboarding.ts': workflowFile() })

        await runCli(['check', 'flows/onboarding.ts'], {
            workspace,
            env: { POSTHOG_CLI_API_KEY: 'phx_test', POSTHOG_CLI_PROJECT_ID: '2', POSTHOG_CLI_HOST: standIn.url },
        })

        assert.match(String(standIn.requests[0]?.headers['user-agent']), /^posthog-workflows\/\d+\.\d+\.\d+$/)
        assert.equal(standIn.requests[0]?.headers['authorization'], 'Bearer phx_test')
        assert.match(standIn.requests[0]?.url ?? '', /^\/api\/environments\/2\/hog_flows\/\?key=onboarding-nudge$/)
    })
})
