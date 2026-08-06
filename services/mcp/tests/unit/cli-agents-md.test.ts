import * as fs from 'node:fs/promises'
import * as os from 'node:os'
import * as path from 'node:path'
import { describe, expect, it } from 'vitest'

import { AGENTS_MD_SNIPPET, installAgentsMdSnippet } from '@/cli/agents-md'

describe('CLI AGENTS.md installer', () => {
    it('wraps the installed snippet in a <posthog> block', () => {
        expect(AGENTS_MD_SNIPPET.startsWith('<posthog>\n')).toBe(true)
        expect(AGENTS_MD_SNIPPET.endsWith('\n</posthog>')).toBe(true)
    })

    it('installs the snippet idempotently', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-agents-md-'))
        const target = path.join(dir, 'AGENTS.md')
        await fs.writeFile(target, '# Project\n\nExisting instructions.\n')

        await installAgentsMdSnippet({ filePath: target })
        await installAgentsMdSnippet({ filePath: target })

        const content = await fs.readFile(target, 'utf-8')
        expect(content.match(/<posthog>/g)?.length).toBe(1)
        expect(content).toContain('Existing instructions.')
    })

    it('replaces a stale <posthog> block in place', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-agents-md-'))
        const target = path.join(dir, 'AGENTS.md')
        await fs.writeFile(
            target,
            '# Project\n\n<posthog>\nOutdated PostHog guidance.\n</posthog>\n\nTrailing instructions.\n'
        )

        await installAgentsMdSnippet({ filePath: target })

        const content = await fs.readFile(target, 'utf-8')
        expect(content).not.toContain('Outdated PostHog guidance.')
        expect(content.match(/<posthog>/g)?.length).toBe(1)
        expect(content.indexOf('# Project')).toBeLessThan(content.indexOf('<posthog>'))
        expect(content.indexOf('</posthog>')).toBeLessThan(content.indexOf('Trailing instructions.'))
    })
})
