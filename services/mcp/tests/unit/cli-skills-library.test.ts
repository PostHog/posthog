import { strToU8, unzipSync, zipSync } from 'fflate'
import * as fs from 'node:fs/promises'
import * as os from 'node:os'
import * as path from 'node:path'
import { describe, expect, it } from 'vitest'

import type { LearnRequest, LearnResult, SkillsFetch, SkillsResult } from '@/cli/library-types'
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

function contextMill(): Uint8Array {
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
        'audit.zip': zipSync({ 'SKILL.md': strToU8('# Audit\n') }),
        'omnibus-instrument-integration.zip': zipSync({
            'SKILL.md': skillFile(
                'omnibus-instrument-integration',
                'Add PostHog SDK integration.',
                '# Integrate\n\nRead `learn posthog:instrument-integration references/COMMANDMENTS.md` first.'
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

const FUNNELS: LearnRequest = { skill: 'posthog:funnels', paths: [] }
const LIST: LearnRequest = { skill: 'skills', paths: [] }

const ONLINE = { [PRODUCT_SKILL_ARCHIVE_URL]: productSkills(), [CONTEXT_MILL_URL]: contextMill() }
const FIRST_LOAD = Date.UTC(2026, 0, 1)

async function cacheDir(): Promise<string> {
    return fs.mkdtemp(path.join(os.tmpdir(), 'posthog-skills-cache-'))
}

async function warmCache(dir: string, assets = ONLINE): Promise<void> {
    const library = createSkillsLibrary({ cacheDir: dir, fetch: fakeFetch(assets).fetch, now: () => FIRST_LOAD })
    const result = await library.learn(LIST)
    expect(result.ok).toBe(true)
}

function text(result: SkillsResult<LearnResult>): string {
    if (!result.ok || result.value.output.kind !== 'text') {
        throw new Error(`Expected text, got ${JSON.stringify(result)}`)
    }
    return result.value.output.text
}

describe('CLI skills library', () => {
    it('serves PostHog and context-mill skills, records each read, and names commands in the caller syntax', async () => {
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: fakeFetch(ONLINE).fetch,
            learnCommand: 'hog learn',
        })

        const skill = await library.learn({ skill: 'posthog:instrument-integration', paths: [] })
        const file = await library.learn({
            skill: 'posthog:instrument-integration',
            paths: ['references/COMMANDMENTS.md'],
        })
        const listing = await library.learn(LIST)

        expect(text(skill)).toContain(
            'Read `hog learn posthog:instrument-integration references/COMMANDMENTS.md` first.'
        )
        expect(text(skill)).toContain('Read a file with `hog learn posthog:instrument-integration <path>`')
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
        expect(listing.ok && listing.value.output).toEqual({
            kind: 'list',
            skills: ['posthog:funnels', 'posthog:instrument-integration'],
            count: 2,
            truncated: false,
        })
    })

    it('uses the network copy when the download works, even with an older copy cached', async () => {
        const dir = await cacheDir()
        await warmCache(dir, { ...ONLINE, [PRODUCT_SKILL_ARCHIVE_URL]: productSkills('Old body.') })
        const library = createSkillsLibrary({
            cacheDir: dir,
            fetch: fakeFetch(ONLINE).fetch,
            now: () => FIRST_LOAD + 60_000,
        })

        const result = await library.learn(FUNNELS)

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

        const result = await library.learn(FUNNELS)

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

        const result = await library.learn(FUNNELS)

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

        const result = await library.learn(FUNNELS)

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

        const result = await library.learn(FUNNELS)

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

        const result = await library.learn(FUNNELS)

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

        const offline = await library.learn(FUNNELS)
        Object.assign(answers, ONLINE)
        const online = await library.learn(FUNNELS)

        expect(offline).toMatchObject({ ok: false, error: { code: 'offline' } })
        expect(text(online)).toContain('Build a conversion funnel.')
    })

    it('keeps the product skills it downloaded while context-mill is down, and asks again only for context-mill', async () => {
        const assets = fakeFetch({ [PRODUCT_SKILL_ARCHIVE_URL]: productSkills() })
        const library = createSkillsLibrary({ fetch: assets.fetch })

        await library.learn(FUNNELS)
        const second = await library.learn(FUNNELS)

        expect(text(second)).toContain('Build a conversion funnel.')
        expect(assets.requests.map((request) => request.url)).toEqual([
            PRODUCT_SKILL_ARCHIVE_URL,
            CONTEXT_MILL_URL,
            CONTEXT_MILL_URL,
        ])
    })

    it('lists the commands without the network, and treats empty words as absent', async () => {
        const assets = fakeFetch({})
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: assets.fetch,
            learnCommand: 'hog learn',
        })

        const result = await library.learn({ skill: ' ', paths: ['', ' '] })

        expect(result.ok && result.value.output).toMatchObject({
            kind: 'overview',
            commands: expect.arrayContaining(['hog learn skills']),
        })
        expect(assets.requests).toEqual([])
    })

    it('serves the product skills alone when context-mill is unavailable', async () => {
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: fakeFetch({ [PRODUCT_SKILL_ARCHIVE_URL]: productSkills() }).fetch,
        })

        const result = await library.learn(LIST)

        expect(result.ok && result.value.output).toMatchObject({ kind: 'list', skills: ['posthog:funnels'] })
        expect(result.ok && result.value.assets[1]).toMatchObject({
            name: 'context-mill',
            origin: 'unavailable',
        })
    })

    it.each<[string, LearnRequest, string]>([
        ['a search of every skill', { paths: [], search: 'conversion' }, '## posthog:funnels'],
        [
            'a search of one file',
            { skill: 'posthog:funnels', paths: ['SKILL.md'], search: 'conversion' },
            'Matches in posthog:funnels/SKILL.md',
        ],
        [
            'a description of several skills',
            { skill: 'posthog:funnels', paths: ['posthog:instrument-integration'], describe: true },
            'posthog:instrument-integration: Add PostHog SDK integration.',
        ],
        [
            'a line range',
            { skill: 'posthog:funnels', paths: ['SKILL.md'], lines: '1:1' },
            'File: posthog:funnels/SKILL.md lines 1:1',
        ],
    ])('serves %s', async (_name, request, expected) => {
        const library = createSkillsLibrary({ fetch: fakeFetch(ONLINE).fetch })

        const result = await library.learn(request)

        expect(text(result)).toContain(expected)
    })

    it('lists the setup skills from context-mill alone', async () => {
        const assets = fakeFetch(ONLINE)
        const library = createSkillsLibrary({ fetch: assets.fetch })

        const result = await library.instrumentSkills()

        expect(result.ok && result.value.skills).toEqual(['posthog:instrument-integration'])
        expect(assets.requests.map((request) => request.url)).toEqual([CONTEXT_MILL_URL])
    })

    it.each<[LearnRequest, string, string]>([
        [{ skill: 'posthog:missing', paths: [] }, 'unknown_skill', 'Use `hog learn -s <query>` to find a skill.'],
        [
            { skill: 'posthog:funnels', paths: ['missing.md'] },
            'unknown_file',
            'Run `hog learn posthog:funnels` for its manifest.',
        ],
        [{ skill: 'funnels', paths: [] }, 'unknown_topic', 'Unknown learning topic: "funnels".'],
        [{ skill: 'project:conventions', paths: [] }, 'unavailable', 'This CLI serves PostHog skills only.'],
        [
            { skill: 'posthog:funnels', paths: ['SKILL.md'], lines: 'ten' },
            'usage',
            'Usage: hog learn <source>:<skill> <path> --lines',
        ],
        [
            { skill: 'posthog:funnels', paths: ['SKILL.md'], lines: '1:2', search: 'funnel' },
            'usage',
            'Give only one of search, describe and lines.',
        ],
    ])('learn %j fails with %s', async (request, code, message) => {
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: fakeFetch(ONLINE).fetch,
            learnCommand: 'hog learn',
        })

        const result = await library.learn(request)

        expect(result).toEqual({ ok: false, error: { code, message: expect.stringContaining(message) } })
    })

    it('installs a batch from the release installable listed, without asking the network again', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-skills-install-'))
        const cache = await cacheDir()
        await warmCache(cache)
        const outage = fakeFetch({ [CONTEXT_MILL_URL]: new TypeError('Unable to connect') })
        const library = createSkillsLibrary({ cacheDir: cache, fetch: outage.fetch })

        const listed = await library.installable()
        const release = listed.ok ? listed.value.release : undefined
        const installed = await library.install('audit', { cwd: dir, release })
        const again = await library.install('audit', { cwd: dir, skillsDir: '.claude/skills', release })
        const unknown = await library.install('missing', { cwd: dir, release })

        expect(installed.ok && installed.value.skill.fileCount).toBe(1)
        expect(again.ok && again.value.assets).toEqual([expect.objectContaining({ origin: 'cache' })])
        await expect(fs.readFile(path.join(dir, '.agents', 'skills', 'audit', 'SKILL.md'), 'utf8')).resolves.toBe(
            '# Audit\n'
        )
        await expect(fs.readFile(path.join(dir, '.claude', 'skills', 'audit', 'SKILL.md'), 'utf8')).resolves.toBe(
            '# Audit\n'
        )
        expect(unknown).toEqual({ ok: false, error: { code: 'unknown_skill', message: 'Unknown skill "missing".' } })
        expect(outage.requests.map((request) => request.url)).toEqual([CONTEXT_MILL_URL])
    })

    it('refuses to install a skill whose archive is past the extraction limit, and keeps the installed copy', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-skills-install-'))
        const installed = path.join(dir, '.agents', 'skills', 'audit', 'SKILL.md')
        await fs.mkdir(path.dirname(installed), { recursive: true })
        await fs.writeFile(installed, '# Installed\n')
        const release = unzipSync(contextMill())
        release['audit.zip'] = zipSync({ 'SKILL.md': strToU8('# Audit\n'), 'big.bin': new Uint8Array(9 * MIB) })
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
        ['a backticked command', 'hog learn', 'Run `learn -s <query>`.', 'Run `hog learn -s <query>`.'],
        [
            'an exec tool call',
            'hog learn',
            'posthog:exec({"command": "learn posthog:funnels"})',
            'hog learn posthog:funnels',
        ],
        [
            'an exec tool call with the default command',
            'learn',
            'posthog:exec({"command": "learn posthog:funnels"})',
            'learn posthog:funnels',
        ],
        [
            'an exec call to another verb',
            'hog learn',
            'posthog:exec({"command": "search flags"})',
            'posthog:exec({"command": "search flags"})',
        ],
        [
            'a usage line',
            'hog learn',
            'Usage: learn <source>:<skill> <path>',
            'Usage: hog learn <source>:<skill> <path>',
        ],
        [
            'prose',
            'hog learn',
            'Agents learn skills fast. To learn more, see the docs.',
            'Agents learn skills fast. To learn more, see the docs.',
        ],
    ])('rewrites %s', (_name, learnCommand, input, expected) => {
        expect(rewriteLearnCommands(input, learnCommand)).toBe(expected)
    })
})
