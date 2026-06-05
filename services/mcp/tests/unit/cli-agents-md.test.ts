import * as fs from 'node:fs/promises'
import * as os from 'node:os'
import * as path from 'node:path'
import { describe, expect, it } from 'vitest'

import { AGENTS_MD_PROMPT, installAgentsMdSnippet } from '@/cli/agents-md'

describe('CLI AGENTS.md installer', () => {
    it('loads the canonical PostHog CLI guidance snippet', () => {
        expect(AGENTS_MD_PROMPT).toContain('required progressive disclosure workflow')
        expect(AGENTS_MD_PROMPT).toContain('This `info` step is required before every `call`')
        expect(AGENTS_MD_PROMPT).not.toContain('posthog-cli-api:start')
    })

    it('creates an AGENTS.md file with PostHog CLI guidance', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-agents-md-'))
        const target = await installAgentsMdSnippet({ cwd: dir })
        const content = await fs.readFile(target, 'utf-8')

        expect(target).toBe(path.join(dir, 'AGENTS.md'))
        expect(content).toContain('required progressive disclosure workflow')
        expect(content).toContain('posthog-cli api search <term>')
        expect(content).toContain('This `info` step is required before every `call`')
        expect(content).toContain('Inspect the expected input schema')
        expect(content).toContain('POSTHOG_CLI_EXPERIMENTAL_API=1')
        expect(content).toContain('Prefer `posthog-cli api` over direct MCP tool calls')
        expect(content).toContain('posthog-cli api skill list')
        expect(content).not.toContain('posthog-cli-api:start')
        expect(content).not.toContain('posthog-cli-api:end')
    })

    it('installs the snippet idempotently', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-agents-md-'))
        const target = path.join(dir, 'AGENTS.md')
        await fs.writeFile(target, '# Project\n\nExisting instructions.\n')

        await installAgentsMdSnippet({ filePath: target })
        await installAgentsMdSnippet({ filePath: target })

        const content = await fs.readFile(target, 'utf-8')
        expect(content.match(/required progressive disclosure workflow/g)?.length).toBe(1)
        expect(content).toContain('Existing instructions.')
    })
})
