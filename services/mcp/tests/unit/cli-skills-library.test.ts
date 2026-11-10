import { strToU8, zipSync } from 'fflate'
import * as fs from 'node:fs/promises'
import * as os from 'node:os'
import * as path from 'node:path'
import { describe, expect, it, vi } from 'vitest'

import type { LearnResult, SkillsFetch, SkillsResult } from '@/cli/library-types'
import { createSkillsLibrary, rewriteLearnCommands } from '@/cli/skills-library'
import { CONTEXT_MILL_URL } from '@/resources/internals'
import { PRODUCT_SKILL_ARCHIVE_URL } from '@/skills/skill-catalog'

// A filesystem boundary that tests can pause, to interleave two runs that share a cache folder.
vi.mock('node:fs/promises', async (importOriginal) => {
    const actual = await importOriginal<typeof import('node:fs/promises')>()
    return { ...actual, readFile: vi.fn(actual.readFile) }
})

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

const ONLINE = { [PRODUCT_SKILL_ARCHIVE_URL]: productSkills(), [CONTEXT_MILL_URL]: contextMill() }
const FIRST_LOAD = Date.UTC(2026, 0, 1)

async function cacheDir(): Promise<string> {
    return fs.mkdtemp(path.join(os.tmpdir(), 'posthog-skills-cache-'))
}

async function warmCache(dir: string, assets = ONLINE): Promise<void> {
    const library = createSkillsLibrary({ cacheDir: dir, fetch: fakeFetch(assets).fetch, now: () => FIRST_LOAD })
    const result = await library.learn(['skills'])
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

        const skill = await library.learn(['posthog:instrument-integration'])
        const file = await library.learn(['posthog:instrument-integration', 'references/COMMANDMENTS.md'])
        const listing = await library.learn(['skills'])

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

        const result = await library.learn(['posthog:funnels'])

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

        const result = await library.learn(['posthog:funnels'])

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
            zipSync({ 'padding/big.bin': new Uint8Array(9 * MIB) }),
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

        const result = await library.learn(['posthog:funnels'])

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

        const result = await library.learn(['posthog:funnels'])

        expect(text(result)).toContain('Build a conversion funnel.')
        expect(result.ok && result.value.assets[0]?.origin).toBe('cache')
        expect(cancelled).toBe(true)
    })

    it('keeps the copy another run cached while this run was answering a 304', async () => {
        const dir = await cacheDir()
        await warmCache(dir)
        const actual = await vi.importActual<typeof import('node:fs/promises')>('node:fs/promises')
        const readFile = vi.mocked(fs.readFile)
        let raced = false
        readFile.mockImplementation(async (...args: Parameters<typeof actual.readFile>) => {
            const contents = await actual.readFile(...args)
            if (!raced && /product-skills-[a-f0-9]+\.zip$/.test(String(args[0]))) {
                raced = true
                await warmCache(dir, { ...ONLINE, [PRODUCT_SKILL_ARCHIVE_URL]: productSkills('Newer body.') })
            }
            return contents
        })
        const notModified = { [PRODUCT_SKILL_ARCHIVE_URL]: new Response(null, { status: 304 }) }
        const offlineAnswers = {
            [PRODUCT_SKILL_ARCHIVE_URL]: new TypeError('Unable to connect'),
            [CONTEXT_MILL_URL]: new TypeError('Unable to connect'),
        }

        try {
            await createSkillsLibrary({ cacheDir: dir, fetch: fakeFetch({ ...ONLINE, ...notModified }).fetch }).learn([
                'posthog:funnels',
            ])
        } finally {
            readFile.mockImplementation(actual.readFile)
        }
        const offline = await createSkillsLibrary({ cacheDir: dir, fetch: fakeFetch(offlineAnswers).fetch }).learn([
            'posthog:funnels',
        ])

        expect(raced).toBe(true)
        expect(text(offline)).toContain('Newer body.')
    })

    it('never deletes outside the cache folder for a record whose digest is a path', async () => {
        const root = await cacheDir()
        const dir = path.join(root, 'cache')
        await fs.mkdir(dir)
        await fs.writeFile(path.join(root, 'old.zip'), 'keep')
        const record = { url: PRODUCT_SKILL_ARCHIVE_URL, sha256: '/../../old', fetchedAt: '2026-01-01T00:00:00.000Z' }
        await fs.writeFile(path.join(dir, 'product-skills.json'), JSON.stringify(record))

        await warmCache(dir)

        await expect(fs.readFile(path.join(root, 'old.zip'), 'utf8')).resolves.toBe('keep')
    })

    it('fails as offline when nothing downloads and nothing is cached', async () => {
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: fakeFetch({
                [PRODUCT_SKILL_ARCHIVE_URL]: new TypeError('Unable to connect'),
                [CONTEXT_MILL_URL]: new TypeError('Unable to connect'),
            }).fetch,
        })

        const result = await library.learn(['posthog:funnels'])

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

        const offline = await library.learn(['posthog:funnels'])
        Object.assign(answers, ONLINE)
        const online = await library.learn(['posthog:funnels'])

        expect(offline).toMatchObject({ ok: false, error: { code: 'offline' } })
        expect(text(online)).toContain('Build a conversion funnel.')
    })

    it('lists the commands without the network, and treats empty words as absent', async () => {
        const assets = fakeFetch({})
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: assets.fetch,
            learnCommand: 'hog learn',
        })

        const result = await library.learn(['', ' '])

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

        const result = await library.learn(['skills'])

        expect(result.ok && result.value.output).toMatchObject({ kind: 'list', skills: ['posthog:funnels'] })
        expect(result.ok && result.value.assets[1]).toMatchObject({
            name: 'context-mill',
            origin: 'unavailable',
        })
    })

    it.each([
        [['posthog:missing'], 'unknown_skill', 'Use `hog learn -s <query>` to find a skill.'],
        [['posthog:funnels', 'missing.md'], 'unknown_file', 'Run `hog learn posthog:funnels` for its manifest.'],
        [['funnels'], 'unknown_topic', 'Unknown learning topic: "funnels".'],
        [['project:conventions'], 'unavailable', 'This CLI serves PostHog skills only.'],
        [
            ['posthog:funnels', 'SKILL.md', '--lines', 'ten'],
            'usage',
            'Usage: hog learn <source>:<skill> <path> --lines',
        ],
    ])('learn %j fails with %s', async (words, code, message) => {
        const library = createSkillsLibrary({
            cacheDir: await cacheDir(),
            fetch: fakeFetch(ONLINE).fetch,
            learnCommand: 'hog learn',
        })

        const result = await library.learn(words)

        expect(result).toEqual({ ok: false, error: { code, message: expect.stringContaining(message) } })
    })

    it('installs a context-mill skill from the downloaded release', async () => {
        const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'posthog-skills-install-'))
        const library = createSkillsLibrary({ cacheDir: await cacheDir(), fetch: fakeFetch(ONLINE).fetch })

        const installed = await library.install('audit', { cwd: dir })
        const unknown = await library.install('missing', { cwd: dir })

        expect(installed.ok && installed.value.skill.fileCount).toBe(1)
        await expect(fs.readFile(path.join(dir, '.agents', 'skills', 'audit', 'SKILL.md'), 'utf8')).resolves.toBe(
            '# Audit\n'
        )
        expect(unknown).toMatchObject({ ok: false, error: { code: 'unknown_skill' } })
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
            'a command already in the caller syntax',
            'hog learn',
            'Run `hog learn -s <query>`.',
            'Run `hog learn -s <query>`.',
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
