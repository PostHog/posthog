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

    it.each([
        ['an existing file', true],
        ['a missing file', false],
    ])('refuses to follow an AGENTS.md symlink to %s outside the working directory', async (_label, exists) => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-agents-md-'))
        const outside = path.join(await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-agents-md-outside-')), 'target.md')
        if (exists) {
            await fs.writeFile(outside, 'Outside content.\n')
        }
        await fs.symlink(outside, path.join(dir, 'AGENTS.md'))

        await expect(installAgentsMdSnippet({ cwd: dir })).rejects.toThrow('Refusing to write outside')
        const outsideAfter = await fs.readFile(outside, 'utf-8').catch(() => null)
        expect(outsideAfter).toBe(exists ? 'Outside content.\n' : null)
    })

    it('follows a link inside the target before applying a later ..', async () => {
        const base = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-agents-md-'))
        const dir = path.join(base, 'checkout')
        await fs.mkdir(path.join(base, 'outside', 'subdir'), { recursive: true })
        await fs.mkdir(dir)
        await fs.symlink('../outside/subdir', path.join(dir, 'redirect'))
        await fs.symlink('redirect/../target.md', path.join(dir, 'AGENTS.md'))

        await expect(installAgentsMdSnippet({ cwd: dir })).rejects.toThrow('Refusing to write outside')
        await expect(fs.access(path.join(base, 'outside', 'target.md'))).rejects.toMatchObject({ code: 'ENOENT' })
    })

    it.runIf(path.sep === '/')('treats a backslash in a link target as part of a file name', async () => {
        const base = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-agents-md-'))
        const dir = path.join(base, 'checkout')
        await fs.mkdir(path.join(base, 'outside'), { recursive: true })
        await fs.mkdir(dir)
        await fs.symlink('../outside', path.join(dir, 'safe\\dir'))
        await fs.symlink('safe\\dir/target.md', path.join(dir, 'AGENTS.md'))

        await expect(installAgentsMdSnippet({ cwd: dir })).rejects.toThrow('Refusing to write outside')
        await expect(fs.access(path.join(base, 'outside', 'target.md'))).rejects.toMatchObject({ code: 'ENOENT' })
    })

    it('writes through an AGENTS.md symlink to a missing file inside the working directory', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-agents-md-'))
        await fs.symlink('CLAUDE.md', path.join(dir, 'AGENTS.md'))

        await installAgentsMdSnippet({ cwd: dir })

        await expect(fs.readFile(path.join(dir, 'CLAUDE.md'), 'utf-8')).resolves.toContain('<posthog>')
    })
})
