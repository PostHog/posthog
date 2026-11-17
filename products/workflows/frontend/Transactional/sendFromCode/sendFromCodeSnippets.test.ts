import { execFileSync } from 'child_process'
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'fs'
import { tmpdir } from 'os'
import { join } from 'path'

import { SendFromCodeSdk, SendFromCodeSnippetInput, sendFromCodeSnippet } from './sendFromCodeSnippets'

const SENDER = `"Bob's \\"Shop\\"\nOutlet" <hello@example.com>`

const input = (from: string | null): SendFromCodeSnippetInput => ({
    projectToken: 'phc_test',
    host: 'https://us.i.posthog.com',
    appHost: null,
    sendUrl: 'https://us.posthog.com/api/projects/1/messaging/send/email/',
    from,
})

const FAKE_SDKS: Record<Exclude<SendFromCodeSdk, 'curl'>, { file: string; module: Record<string, string> }> = {
    node: {
        file: 'snippet.mjs',
        module: {
            'node_modules/posthog-node/package.json': '{"name": "posthog-node", "type": "module", "main": "index.js"}',
            'node_modules/posthog-node/index.js': `import { writeFileSync } from 'fs'

export class PostHog {
    emails = {
        send: async (params) => {
            writeFileSync('sent.json', JSON.stringify(params))
            return { data: { id: 'email-id' }, error: null }
        },
    }
}`,
        },
    },
    python: {
        file: 'snippet.py',
        module: {
            'posthog/__init__.py': `import json

class _Emails:
    def send(self, **params):
        with open("sent.json", "w") as sent:
            sent_params = {"idempotencyKey": params.get("idempotency_key")}
            if "from_" in params:
                sent_params["from"] = params["from_"]
            json.dump(sent_params, sent)
        return type("Result", (), {"id": "email-id"})()

class Posthog:
    def __init__(self, *args, **kwargs):
        self.emails = _Emails()
`,
        },
    },
}

function sentParams(sdk: SendFromCodeSdk, code: string): Record<string, unknown> {
    const dir = mkdtempSync(join(tmpdir(), 'send-from-code-'))
    try {
        const env = { PATH: process.env.PATH, POSTHOG_PROJECT_SECRET_API_KEY: 'phs_test' }
        if (sdk === 'curl') {
            writeFileSync(join(dir, 'snippet.sh'), code)
            const args = execFileSync('bash', ['-c', `curl() { printf '%s\\0' "$@"; }; . ./snippet.sh`], {
                cwd: dir,
                env,
            })
                .toString()
                .split('\0')
            const headers = args.flatMap((arg, i) => (args[i - 1] === '-H' ? [arg] : []))
            const idempotencyKey = headers
                .find((header) => header.startsWith('Idempotency-Key: '))
                ?.slice('Idempotency-Key: '.length)
            return { ...JSON.parse(args[args.indexOf('-d') + 1]), idempotencyKey }
        }
        const { file, module } = FAKE_SDKS[sdk]
        for (const [path, source] of Object.entries(module)) {
            mkdirSync(join(dir, path, '..'), { recursive: true })
            writeFileSync(join(dir, path), source)
        }
        writeFileSync(join(dir, file), code)
        execFileSync(sdk === 'node' ? process.execPath : 'python3', [file], { cwd: dir, env })
        return JSON.parse(readFileSync(join(dir, 'sent.json'), 'utf8'))
    } finally {
        rmSync(dir, { recursive: true, force: true })
    }
}

describe('sendFromCodeSnippet', () => {
    test.each<SendFromCodeSdk>(['node', 'python', 'curl'])('sends a quoted sender intact from %s', (sdk) => {
        expect(sentParams(sdk, sendFromCodeSnippet(sdk, input(SENDER)).code).from).toEqual(SENDER)
    })

    test.each<SendFromCodeSdk>(['node', 'python', 'curl'])('sends one idempotency key per email from %s', (sdk) => {
        expect(sentParams(sdk, sendFromCodeSnippet(sdk, input(SENDER)).code).idempotencyKey).toEqual(
            'welcome-jane-distinct-id'
        )
    })

    test.each<SendFromCodeSdk>(['node', 'python', 'curl'])('sends no sender from %s without one', (sdk) => {
        expect(sentParams(sdk, sendFromCodeSnippet(sdk, input(null)).code)).not.toHaveProperty('from')
    })
})
