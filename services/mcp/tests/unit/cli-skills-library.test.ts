import { strToU8, unzipSync, zipSync } from 'fflate'
import * as fs from 'node:fs/promises'
import * as os from 'node:os'
import * as path from 'node:path'
import { describe, expect, it } from 'vitest'

import type {
    SkillCommands,
    SkillReadRequest,
    SkillReadResult,
    SkillsFetch,
    SkillsLibrary,
    SkillsResult,
} from '@/cli/library-types'
import { createSkillsLibrary, rewriteLearnCommands } from '@/cli/skills-library'
import { CONTEXT_MILL_URL } from '@/resources/internals'
import { PRODUCT_SKILL_ARCHIVE_URL } from '@/skills/skill-catalog'

const MIB = 1024 * 1024

function skillFile(name: string, description: string, body: string): Uint8Array {
    return strToU8(`---\nname: ${name}\ndescription: ${description}\n---\n\n${body}`)
}

function productSkills(body = 'Build a conversion funnel.'): Uint8Array {
    return zipSync({ 'funnels/SKILL.md': skillFile('funnels', 'Analyze conversion funnels.', `# Funnels\n\n${body}`) })
}

const AUDIT_SKILL = skillFile('audit', 'Audit an install.', '# Audit\n\nCheck every event.')

function contextMill(auditSkill = AUDIT_SKILL): Uint8Array {
    const manifest = {
        version: '1.0',
        resources: [
            {
                id: 'audit',
                name: 'Audit',
                uri: 'posthog://skills/audit',
                file: 'audit.zip',
                resource: { mimeType: 'text/markdown', description: 'Audit an install.', text: '# Audit' },
            },
        ],
    }
    return zipSync({
        'manifest.json': strToU8(JSON.stringify(manifest)),
        'audit.zip': zipSync({ 'SKILL.md': auditSkill }),
        'omnibus-instrument-integration.zip': zipSync({
            'SKILL.md': skillFile(
                'omnibus-instrument-integration',
                'Add PostHog SDK integration.',
                '# Integrate\n\nRead `learn posthog:instrument-integration references/COMMANDMENTS.md` first. Run `learn skills` for the rest.'
            ),
            'references/COMMANDMENTS.md': strToU8('# Commandments\n\nNever hardcode the token.'),
        }),
    })
}

interface FakeAssets {
    fetch: SkillsFetch
    requests: { url: string; ifNoneMatch?: string }[]
}

type Answer = Uint8Array | Response | Error | 'hang'

function fakeFetch(answers: Partial<Record<string, Answer>>): FakeAssets {
    const requests: FakeAssets['requests'] = []
    return {
        requests,
        fetch: async (url, init) => {
            requests.push({ url, ifNoneMatch: init.headers['If-None-Match'] })
            const answer = answers[url]
            if (answer === 'hang') {
                return new Promise((_resolve, reject) =>
                    init.signal.addEventListener('abort', () => reject(init.signal.reason))
                )
            }
            if (answer instanceof Error) {
                throw answer
            }
            if (answer instanceof Response) {
                return answer
            }
            if (!answer) {
                return new Response('missing', { status: 404 })
            }
            return new Response(new Uint8Array(answer), {
                status: 200,
                headers: { etag: `"${url.length}-${answer.length}"` },
            })
        },
    }
}

const FUNNELS: SkillReadRequest = { skill: 'posthog:funnels' }

const HOG: SkillCommands = {
    read: (skill, file, lines) =>
        `hog skills read ${skill}${file === undefined ? '' : ` --file ${file}`}${lines === undefined ? '' : ` --lines ${lines}`}`,
    search: (keywords) => `hog skills search ${keywords}`,
    list: 'hog skills list',
}

const ONLINE = { [PRODUCT_SKILL_ARCHIVE_URL]: productSkills(), [CONTEXT_MILL_URL]: contextMill() }
const FIRST_LOAD = Date.UTC(2026, 0, 1)

async function cacheDir(): Promise<string> {
    return fs.mkdtemp(path.join(os.tmpdir(), 'posthog-skills-cache-'))
}

async function warmCache(dir: string, assets = ONLINE): Promise<void> {
    const library = createSkillsLibrary({ cacheDir: dir, fetch: fakeFetch(assets).fetch, now: () => FIRST_LOAD })
    const result = await library.catalog()
    expect(result.ok).toBe(true)
}

function text(result: SkillsResult<SkillReadResult>): string {
    if (!result.ok) {
        throw new Error(`Expected text, got ${JSON.stringify(result)}`)
    }
    return result.value.text
}

describe('CLI skills library', () => {
    it('serves PostHog and context-mill skills, records each read, and names commands in the caller syntax', async () => {
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: fakeFetch(ONLINE).fetch,
            commands: HOG,
        })

        const skill = await library.read({ skill: 'posthog:instrument-integration' })
        const file = await library.read({ skill: 'instrument-integration', file: 'references/COMMANDMENTS.md' })
        const listing = await library.catalog()
        const resource = await library.read({ skill: 'audit' })

        expect(text(resource)).toContain('Check every event.')
        expect(text(skill)).toContain(
            'Read `hog skills read instrument-integration --file references/COMMANDMENTS.md` first. Run `hog skills list` for the rest.'
        )
        expect(text(skill)).toContain('Read a file with `hog skills read instrument-integration --file <path>`.\n')
        expect(skill.ok && skill.value.reads).toEqual([
            { source: 'posthog', skill: 'instrument-integration', path: 'SKILL.md', readKind: 'skill' },
        ])
        expect(file.ok && file.value.reads).toEqual([
            {
                source: 'posthog',
                skill: 'instrument-integration',
                path: 'references/COMMANDMENTS.md',
                readKind: 'file',
            },
        ])
        expect(listing.ok && listing.value.skills).toEqual([
            { name: 'funnels', kind: 'learning', description: 'Analyze conversion funnels.' },
            { name: 'audit', kind: 'implementation', description: 'Audit an install.' },
            { name: 'instrument-integration', kind: 'implementation', description: 'Add PostHog SDK integration.' },
        ])
    })

    it('uses the network copy when the download works, even with an older copy cached', async () => {
        const dir = await cacheDir()
        await warmCache(dir, { ...ONLINE, [PRODUCT_SKILL_ARCHIVE_URL]: productSkills('Old body.') })
        const library = createSkillsLibrary({
            cacheDir: dir,
            fetch: fakeFetch(ONLINE).fetch,
            now: () => FIRST_LOAD + 60_000,
        })

        const result = await library.read(FUNNELS)

        expect(text(result)).toContain('Build a conversion funnel.')
        expect(result.ok && result.value.assets).toEqual([
            expect.objectContaining({
                name: 'product-skills',
                origin: 'network',
                fetchedAt: '2026-01-01T00:01:00.000Z',
            }),
            expect.objectContaining({ name: 'context-mill', origin: 'network' }),
        ])
    })

    it('serves the cached copy for a 304 and counts it as a network answer', async () => {
        const dir = await cacheDir()
        await warmCache(dir)
        const notModified = { [PRODUCT_SKILL_ARCHIVE_URL]: new Response(null, { status: 304 }) }
        const assets = fakeFetch({ ...ONLINE, ...notModified })
        const library = createSkillsLibrary({ cacheDir: dir, fetch: assets.fetch })

        const result = await library.read(FUNNELS)

        expect(text(result)).toContain('Build a conversion funnel.')
        expect(result.ok && result.value.assets[0]?.origin).toBe('network')
        expect(assets.requests.find((request) => request.url === PRODUCT_SKILL_ARCHIVE_URL)?.ifNoneMatch).toMatch(/^"/)
    })

    it.each([
        ['a network error', new TypeError('Unable to connect'), 'Unable to connect'],
        ['an HTTP error', new Response('down', { status: 503 }), 'HTTP 503'],
        ['an archive that does not parse', strToU8('not a zip'), 'The downloaded archive is not valid'],
        ['no response before the timeout', 'hang' as const, 'No response within 0.05 seconds'],
        [
            'an archive past the extraction limit',
            zipSync({ 'manifest.json': new Uint8Array(9 * MIB) }),
            'exceeds the extraction limit',
        ],
    ])('serves the cached copy after %s, and says when it was fetched', async (_name, answer, failure) => {
        const dir = await cacheDir()
        await warmCache(dir)
        const library = createSkillsLibrary({
            cacheDir: dir,
            fetch: fakeFetch({ [PRODUCT_SKILL_ARCHIVE_URL]: answer, [CONTEXT_MILL_URL]: answer }).fetch,
            responseTimeoutMs: 50,
        })

        const result = await library.read(FUNNELS)

        expect(text(result)).toContain('Build a conversion funnel.')
        expect(result.ok && result.value.assets[0]).toEqual({
            name: 'product-skills',
            url: PRODUCT_SKILL_ARCHIVE_URL,
            origin: 'cache',
            fetchedAt: '2026-01-01T00:00:00.000Z',
            failure: expect.stringContaining(failure),
        })
        expect(result.ok && result.value.assets[1]).toMatchObject({
            name: 'context-mill',
            origin: 'cache',
            failure: expect.stringContaining(failure),
        })
    })

    it.each([
        ['an HTTP error', 503, {}],
        ['a Content-Length over the limit', 200, { 'content-length': String(65 * MIB) }],
        ['a body that grows past the limit', 200, {}],
    ])('stops reading the body after %s and serves the cached copy', async (_name, status, headers) => {
        const dir = await cacheDir()
        await warmCache(dir)
        const chunk = new Uint8Array(MIB)
        let chunks = 0
        let cancelled = false
        const body = new ReadableStream<Uint8Array>({
            pull(controller) {
                chunks += 1
                if (chunks > 80) {
                    controller.close()
                } else {
                    controller.enqueue(chunk)
                }
            },
            cancel() {
                cancelled = true
            },
        })
        const library = createSkillsLibrary({
            cacheDir: dir,
            fetch: fakeFetch({ ...ONLINE, [PRODUCT_SKILL_ARCHIVE_URL]: new Response(body, { status, headers }) }).fetch,
        })

        const result = await library.read(FUNNELS)

        expect(text(result)).toContain('Build a conversion funnel.')
        expect(result.ok && result.value.assets[0]?.origin).toBe('cache')
        expect(cancelled).toBe(true)
    })

    it('downloads the whole asset again for a 304 when the cached copy no longer matches its record', async () => {
        const dir = await cacheDir()
        await warmCache(dir)
        await fs.writeFile(path.join(dir, 'product-skills.zip'), productSkills('Overwritten body.'))
        const online = fakeFetch(ONLINE)
        const productRequests: (string | undefined)[] = []
        const library = createSkillsLibrary({
            cacheDir: dir,
            fetch: async (url, init) => {
                const etag = init.headers['If-None-Match']
                if (url !== PRODUCT_SKILL_ARCHIVE_URL) {
                    return online.fetch(url, init)
                }

                productRequests.push(etag)
                return etag ? new Response(null, { status: 304 }) : online.fetch(url, init)
            },
        })

        const result = await library.read(FUNNELS)

        expect(text(result)).toContain('Build a conversion funnel.')
        expect(productRequests).toEqual([expect.stringMatching(/^"/), undefined])
    })

    it('fails as offline when nothing downloads and nothing is cached', async () => {
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: fakeFetch({
                [PRODUCT_SKILL_ARCHIVE_URL]: new TypeError('Unable to connect'),
                [CONTEXT_MILL_URL]: new TypeError('Unable to connect'),
            }).fetch,
        })

        const result = await library.read(FUNNELS)

        expect(result).toEqual({
            ok: false,
            error: {
                code: 'offline',
                message: expect.any(String),
                assets: [
                    expect.objectContaining({
                        name: 'product-skills',
                        origin: 'unavailable',
                        failure: 'Unable to connect',
                    }),
                    expect.objectContaining({
                        name: 'context-mill',
                        origin: 'unavailable',
                        failure: 'Unable to connect',
                    }),
                ],
            },
        })
    })

    it('downloads again on the next call after an outage, in the same process', async () => {
        const answers: Partial<Record<string, Answer>> = {
            [PRODUCT_SKILL_ARCHIVE_URL]: new TypeError('Unable to connect'),
            [CONTEXT_MILL_URL]: new TypeError('Unable to connect'),
        }
        const library = createSkillsLibrary({ cacheDir: await cacheDir(), fetch: fakeFetch(answers).fetch })

        const offline = await library.read(FUNNELS)
        Object.assign(answers, ONLINE)
        const online = await library.read(FUNNELS)

        expect(offline).toMatchObject({ ok: false, error: { code: 'offline' } })
        expect(text(online)).toContain('Build a conversion funnel.')
    })

    it('keeps the product skills it downloaded while context-mill is down, and asks again only for context-mill', async () => {
        const assets = fakeFetch({ [PRODUCT_SKILL_ARCHIVE_URL]: productSkills() })
        const library = createSkillsLibrary({ fetch: assets.fetch })

        await library.read(FUNNELS)
        const second = await library.read(FUNNELS)

        expect(text(second)).toContain('Build a conversion funnel.')
        expect(assets.requests.map((request) => request.url)).toEqual([
            PRODUCT_SKILL_ARCHIVE_URL,
            CONTEXT_MILL_URL,
            CONTEXT_MILL_URL,
        ])
    })

    it('serves the product skills alone when context-mill is unavailable', async () => {
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: fakeFetch({ [PRODUCT_SKILL_ARCHIVE_URL]: productSkills() }).fetch,
        })

        const result = await library.catalog()

        expect(result.ok && result.value.skills).toEqual([
            { name: 'funnels', kind: 'learning', description: 'Analyze conversion funnels.' },
        ])
        expect(result.ok && result.value.assets[1]).toMatchObject({
            name: 'context-mill',
            origin: 'unavailable',
        })
    })

    it.each<[string, SkillReadRequest, string]>([
        ['a line range of SKILL.md', { skill: 'funnels', lines: '1:1' }, 'File: funnels/SKILL.md lines 1:1'],
        [
            'a line range of a file',
            { skill: 'posthog:funnels', file: 'SKILL.md', lines: '1:1' },
            'File: funnels/SKILL.md lines 1:1',
        ],
    ])('serves %s', async (_name, request, expected) => {
        const library = createSkillsLibrary({ fetch: fakeFetch(ONLINE).fetch, commands: HOG })

        const result = await library.read(request)

        expect(text(result)).toContain(expected)
    })

    it('points a file too large to show to a line range, with the heading outline', async () => {
        const body = `## Setup\n\n${'Build a conversion funnel. '.repeat(2_000)}`
        const library = createSkillsLibrary({
            fetch: fakeFetch({ ...ONLINE, [PRODUCT_SKILL_ARCHIVE_URL]: productSkills(body) }).fetch,
            commands: HOG,
        })

        const result = await library.read({ skill: 'funnels' })

        expect(text(result)).toContain(
            'This file is too large to return in full. Read part of it with `hog skills read funnels --file SKILL.md --lines <start>:<end>`, using the line numbers in the heading outline.'
        )
        expect(text(result)).toMatch(/\d+: ## Setup/)
    })

    it('finds skills by keywords, with the lines that match', async () => {
        const library = createSkillsLibrary({ fetch: fakeFetch(ONLINE).fetch, commands: HOG })

        const result = await library.search('conversion funnel')

        expect(result.ok && result.value.skills).toEqual([
            {
                name: 'funnels',
                description: 'Analyze conversion funnels.',
                matches: expect.arrayContaining([expect.objectContaining({ path: 'SKILL.md' })]),
            },
        ])
    })

    it('fails a read of a resource skill whose SKILL.md has no frontmatter, instead of serving its listing', async () => {
        const library = createSkillsLibrary({
            fetch: fakeFetch({ ...ONLINE, [CONTEXT_MILL_URL]: contextMill(strToU8('# Audit\n\nNo frontmatter.')) })
                .fetch,
        })

        const result = await library.read({ skill: 'audit' })

        expect(result).toEqual({
            ok: false,
            error: {
                code: 'unavailable',
                message:
                    'Couldn\'t read the skill "audit", because its archive in the skills release has no valid SKILL.md.',
            },
        })
    })

    it('lists the setup skills from context-mill alone', async () => {
        const assets = fakeFetch(ONLINE)
        const library = createSkillsLibrary({ fetch: assets.fetch })

        const result = await library.instrumentSkills()

        expect(result.ok && result.value.skills).toEqual(['posthog:instrument-integration'])
        expect(assets.requests.map((request) => request.url)).toEqual([CONTEXT_MILL_URL])
    })

    it.each<[string, (library: SkillsLibrary) => Promise<SkillsResult<unknown>>, string, string]>([
        [
            'an unknown skill',
            (library) => library.read({ skill: 'posthog:missing' }),
            'unknown_skill',
            'Unknown skill "posthog:missing".',
        ],
        [
            'an unknown file',
            (library) => library.read({ skill: 'funnels', file: 'missing.md' }),
            'unknown_file',
            'Run `hog skills read funnels` for its manifest.',
        ],
        [
            'lines that are not a range',
            (library) => library.read({ skill: 'funnels', lines: 'ten' }),
            'usage',
            'Give the lines as `<start>:<end>`',
        ],
        [
            'lines past the end of the file',
            (library) => library.read({ skill: 'funnels', lines: '1:999' }),
            'usage',
            'Invalid line range 1:999.',
        ],
        ['a search without keywords', (library) => library.search('  '), 'usage', 'Give between 1 and 200 characters'],
    ])('%s fails', async (_name, call, code, message) => {
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: fakeFetch(ONLINE).fetch,
            commands: HOG,
        })

        const result = await call(library)

        expect(result).toEqual({ ok: false, error: { code, message: expect.stringContaining(message) } })
    })

    it('installs a batch of any listed skills from the catalog it loaded, without asking the network again', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-skills-install-'))
        const cache = await cacheDir()
        await warmCache(cache)
        const outage = fakeFetch({
            [PRODUCT_SKILL_ARCHIVE_URL]: new TypeError('Unable to connect'),
            [CONTEXT_MILL_URL]: new TypeError('Unable to connect'),
        })
        const library = createSkillsLibrary({ cacheDir: cache, fetch: outage.fetch, commands: HOG })

        const listed = await library.catalog()
        const release = listed.ok ? listed.value.release : undefined
        const installed = await library.install('audit', { cwd: dir, release })
        const again = await library.install('posthog:audit', { cwd: dir, skillsDir: '.claude/skills', release })
        const product = await library.install('posthog:funnels', { cwd: dir, release })
        const omnibus = await library.install('posthog:instrument-integration', { cwd: dir, release })
        const unknown = await library.install('missing', { cwd: dir, release })

        expect(installed.ok && installed.value.skill.fileCount).toBe(1)
        expect(again.ok && again.value.assets).toEqual([
            expect.objectContaining({ name: 'product-skills', origin: 'cache' }),
            expect.objectContaining({ name: 'context-mill', origin: 'cache' }),
        ])
        expect(product.ok && product.value.skill.fileCount).toBe(1)
        expect(omnibus.ok && omnibus.value.skill.fileCount).toBe(2)
        const installedFile = (...parts: string[]): Promise<string> => fs.readFile(path.join(dir, ...parts), 'utf8')
        await expect(installedFile('.agents', 'skills', 'audit', 'SKILL.md')).resolves.toContain('Check every event.')
        await expect(installedFile('.claude', 'skills', 'audit', 'SKILL.md')).resolves.toContain('Check every event.')
        await expect(installedFile('.agents', 'skills', 'funnels', 'SKILL.md')).resolves.toContain(
            'Build a conversion funnel.'
        )
        await expect(installedFile('.agents', 'skills', 'instrument-integration', 'SKILL.md')).resolves.toContain(
            'Read `hog skills read instrument-integration --file references/COMMANDMENTS.md` first.'
        )
        expect(unknown).toEqual({ ok: false, error: { code: 'unknown_skill', message: 'Unknown skill "missing".' } })
        expect(outage.requests.map((request) => request.url).sort()).toEqual(
            [PRODUCT_SKILL_ARCHIVE_URL, CONTEXT_MILL_URL].sort()
        )
    })

    it('refuses to install a skill whose archive is past the extraction limit, and keeps the installed copy', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-skills-install-'))
        const installed = path.join(dir, '.agents', 'skills', 'audit', 'SKILL.md')
        await fs.mkdir(path.dirname(installed), { recursive: true })
        await fs.writeFile(installed, '# Installed\n')
        const release = unzipSync(contextMill())
        release['audit.zip'] = zipSync({ 'SKILL.md': AUDIT_SKILL, 'big.bin': new Uint8Array(9 * MIB) })
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: fakeFetch({ ...ONLINE, [CONTEXT_MILL_URL]: zipSync(release) }).fetch,
        })

        const result = await library.install('audit', { cwd: dir, force: true })

        expect(result).toMatchObject({
            ok: false,
            error: { code: 'install_failed', message: expect.stringContaining('exceeds the extraction limit') },
        })
        await expect(fs.readFile(installed, 'utf8')).resolves.toBe('# Installed\n')
    })

    it.each([
        ['a search', 'Run `learn -s <query>`.', 'Run `hog skills search <query>`.'],
        ['the skill list', 'Run `learn skills`.', 'Run `hog skills list`.'],
        ['an exec tool call', 'posthog:exec({"command": "learn posthog:funnels"})', 'hog skills read funnels'],
        [
            'a line range of a file',
            '`learn posthog:funnels references/a.md --lines 1:5`',
            '`hog skills read funnels --file references/a.md --lines 1:5`',
        ],
        ['a usage line', 'Usage: `learn <source>:<skill> <path>`', 'Usage: `hog skills read <skill> --file <path>`'],
        [
            'a batch, as one read each',
            '`learn posthog:funnels posthog:audit`',
            '`hog skills read funnels` and `hog skills read audit`',
        ],
        [
            'a project skill, which the CLI has no command for',
            '`learn project:conventions`',
            '`learn project:conventions`',
        ],
        [
            'an exec call to another verb',
            'posthog:exec({"command": "search flags"})',
            'posthog:exec({"command": "search flags"})',
        ],
        [
            'prose',
            'Agents learn skills fast. To learn more, see the docs.',
            'Agents learn skills fast. To learn more, see the docs.',
        ],
    ])('rewrites %s', (_name, input, expected) => {
        expect(rewriteLearnCommands(input, HOG)).toBe(expected)
    })
})
