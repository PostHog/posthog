import { randomUUID } from 'node:crypto'
import * as fs from 'node:fs/promises'
import * as path from 'node:path'
import { z } from 'zod'

import { hashBytes } from '@/hono/cache/SharedBlobCache'
import { CONTEXT_MILL_URL, contextMillEntries, omnibusSkillFiles, unzipOmnibusArchives } from '@/resources/internals'
import {
    LearnLookupError,
    MAX_SKILL_ARCHIVE_BYTES,
    PRODUCT_SKILL_ARCHIVE_URL,
    SkillCatalog,
    unzipUntrusted,
} from '@/skills/skill-catalog'
import { ExecLearnCatalog, learnSkillCommands, SkillsUnavailableError } from '@/tools/exec-learn'

import type {
    InstallableSkill,
    LearnRequest,
    LearnResult,
    SkillAssetName,
    SkillAssetStatus,
    SkillRead,
    SkillsError,
    SkillsFetch,
    SkillsLibrary,
    SkillsLibraryOptions,
    SkillsRelease,
    SkillsResult,
} from './library-types'
import { installSkill, type InstallableSkills, listSkills, SkillInstallError } from './skills'

const DEFAULT_RESPONSE_TIMEOUT_MS = 5_000
const DEFAULT_DOWNLOAD_TIMEOUT_MS = 60_000
const INSTRUMENT_SKILL_PREFIX = 'instrument-'
const PROJECT_SKILLS_UNAVAILABLE =
    'This CLI serves PostHog skills only. Read project skills through the PostHog MCP server.'

// The server's and posthog-cli's overrides, so a local build of either release can be tested here too.
function assetUrl(name: SkillAssetName): string {
    return name === 'product-skills'
        ? process.env.POSTHOG_MCP_SKILLS_URL || PRODUCT_SKILL_ARCHIVE_URL
        : process.env.POSTHOG_MCP_LOCAL_SKILLS_URL || CONTEXT_MILL_URL
}

const CacheRecord = z.object({
    url: z.string(),
    etag: z.string().optional(),
    sha256: z.string(),
    fetchedAt: z.string(),
})

type CacheRecord = z.output<typeof CacheRecord>

class DownloadError extends Error {}

interface LoadedAsset<T> {
    status: SkillAssetStatus
    parsed?: T
}

interface Settings {
    cacheDir: string | undefined
    fetch: SkillsFetch
    responseTimeoutMs: number
    downloadTimeoutMs: number
    now: () => number
}

function message(error: unknown): string {
    return error instanceof Error ? error.message : String(error)
}

// Keeps a load only once every asset in it came from the network, so a process that outlives a
// network outage downloads again on its next call instead of serving the outage forever.
function memoizeWhileFresh<T extends { assets: readonly SkillAssetStatus[] }>(
    load: () => Promise<T>
): () => Promise<T> {
    let kept: Promise<T> | undefined
    return () => {
        if (kept) {
            return kept
        }
        const loading = load()
        kept = loading

        void loading.then((result) => {
            if (result.assets.some((asset) => asset.origin !== 'network')) {
                kept = undefined
            }
        })
        return loading
    }
}

async function writeAtomically(file: string, contents: Uint8Array | string): Promise<void> {
    const temporary = `${file}.${randomUUID()}.tmp`
    try {
        await fs.writeFile(temporary, contents, { flag: 'wx' })
        await fs.rename(temporary, file)
    } catch (error) {
        await fs.rm(temporary, { force: true })
        throw error
    }
}

interface ContextMillRelease extends InstallableSkills {
    omnibus(): SkillCatalog | undefined
}

interface LoadedRelease {
    release: ContextMillRelease
    assets: SkillAssetStatus[]
}

// The release counts as valid when its manifest loads. Every other file stays zipped until a call
// reads it: a skill's zip to install it, or the omnibus skills for `learn`.
function parseContextMill(bytes: Uint8Array): ContextMillRelease {
    let omnibus: { catalog: SkillCatalog | undefined } | undefined

    return {
        entries: contextMillEntries(bytes),
        readFile: (name) => unzipUntrusted(bytes, 'The context-mill release', (file) => file.name === name)[name],
        omnibus: () => {
            omnibus ??= { catalog: omnibusCatalog(bytes) }
            return omnibus.catalog
        },
    }
}

function omnibusCatalog(release: Uint8Array): SkillCatalog | undefined {
    try {
        const files = omnibusSkillFiles(unzipOmnibusArchives(release))

        return Object.keys(files).length > 0 ? SkillCatalog.fromFiles(files) : undefined
    } catch {
        return undefined
    }
}

// The last good download of one asset: its bytes, and a record that names their hash. Each file is
// replaced atomically, and bytes that don't match the record count as no copy, so a write that stops
// halfway, or two runs that write at once, cost a download instead of serving a wrong copy.
class AssetCache {
    private readonly bytesFile: string
    private readonly recordFile: string

    constructor(
        private readonly folder: string,
        name: SkillAssetName
    ) {
        this.bytesFile = path.join(folder, `${name}.zip`)
        this.recordFile = path.join(folder, `${name}.json`)
    }

    async record(): Promise<CacheRecord | undefined> {
        try {
            const parsed = CacheRecord.safeParse(JSON.parse(await fs.readFile(this.recordFile, 'utf8')))
            return parsed.success ? parsed.data : undefined
        } catch {
            return undefined
        }
    }

    async bytes(record: CacheRecord): Promise<Uint8Array | undefined> {
        try {
            const bytes = await fs.readFile(this.bytesFile)
            return hashBytes(bytes) === record.sha256 ? bytes : undefined
        } catch {
            return undefined
        }
    }

    // A cache that can't be written only costs the next offline run its fallback.
    async write(record: CacheRecord, bytes?: Uint8Array): Promise<void> {
        try {
            await fs.mkdir(this.folder, { recursive: true })

            if (bytes) {
                await writeAtomically(this.bytesFile, bytes)
            }

            await writeAtomically(this.recordFile, JSON.stringify(record))
        } catch {
            return
        }
    }
}

async function readLimited(response: Response): Promise<Uint8Array> {
    const reader = response.body?.getReader()
    const chunks: Uint8Array[] = []
    let size = 0
    for (let chunk = await reader?.read(); chunk && !chunk.done; chunk = await reader?.read()) {
        size += chunk.value.byteLength
        if (size > MAX_SKILL_ARCHIVE_BYTES) {
            await reader?.cancel().catch(() => undefined)
            throw new DownloadError(`The asset is over the ${MAX_SKILL_ARCHIVE_BYTES} byte limit`)
        }
        chunks.push(chunk.value)
    }
    const bytes = new Uint8Array(size)
    let offset = 0
    for (const chunk of chunks) {
        bytes.set(chunk, offset)
        offset += chunk.byteLength
    }
    return bytes
}

/** The asset's bytes and ETag, or undefined when the server answered 304 to `etag`. */
async function download(
    settings: Settings,
    url: string,
    etag: string | undefined
): Promise<{ bytes: Uint8Array; etag?: string } | undefined> {
    const controller = new AbortController()
    const abortAfter = (ms: number, reason: string): ReturnType<typeof setTimeout> => {
        const timer = setTimeout(() => controller.abort(new DownloadError(reason)), ms)
        timer.unref?.()
        return timer
    }
    const { responseTimeoutMs, downloadTimeoutMs } = settings
    let timer = abortAfter(responseTimeoutMs, `No response within ${responseTimeoutMs / 1000} seconds`)
    let response: Response | undefined
    try {
        response = await settings.fetch(url, {
            headers: etag ? { 'If-None-Match': etag } : {},
            signal: controller.signal,
        })
        clearTimeout(timer)
        timer = abortAfter(downloadTimeoutMs, `The download took longer than ${downloadTimeoutMs / 1000} seconds`)
        if (response.status === 304 && etag) {
            return undefined
        }
        if (!response.ok) {
            throw new DownloadError(`HTTP ${response.status}`)
        }
        const length = Number(response.headers.get('content-length'))
        if (Number.isFinite(length) && length > MAX_SKILL_ARCHIVE_BYTES) {
            throw new DownloadError(`The asset is ${length} bytes, over the ${MAX_SKILL_ARCHIVE_BYTES} byte limit`)
        }
        const bytes = await readLimited(response)
        if (bytes.length === 0) {
            throw new DownloadError('The asset is 0 bytes')
        }
        // GitHub redirects release assets to storage, and the final response carries the asset's own ETag.
        return { bytes, etag: response.headers.get('etag') ?? undefined }
    } catch (error) {
        // A body left unread keeps its connection open after the download has failed.
        await response?.body?.cancel().catch(() => undefined)
        throw controller.signal.reason instanceof DownloadError ? controller.signal.reason : error
    } finally {
        clearTimeout(timer)
    }
}

async function loadAsset<T>(
    settings: Settings,
    name: SkillAssetName,
    parse: (bytes: Uint8Array) => T
): Promise<LoadedAsset<T>> {
    const url = assetUrl(name)
    const cache = settings.cacheDir === undefined ? undefined : new AssetCache(settings.cacheDir, name)
    const record = await cache?.record()
    const cached = record?.url === url ? record : undefined

    const readCached = async (): Promise<T | undefined> => {
        const bytes = cached && (await cache?.bytes(cached))
        try {
            return bytes && parse(bytes)
        } catch {
            return undefined
        }
    }
    const fetchedAt = new Date(settings.now()).toISOString()

    try {
        let fresh = await download(settings, url, cached?.etag)
        if (!fresh && cached) {
            const parsed = await readCached()

            if (parsed) {
                await cache?.write({ ...cached, fetchedAt })
                return { status: { name, url, origin: 'network', fetchedAt }, parsed }
            }

            // The cached copy is gone or no longer matches its record, so the 304 can't be served. Ask
            // again for the whole asset.
            fresh = await download(settings, url, undefined)
        }

        if (!fresh) {
            throw new DownloadError('HTTP 304')
        }

        let parsed: T
        try {
            parsed = parse(fresh.bytes)
        } catch (error) {
            throw new DownloadError(`The downloaded archive is not valid: ${message(error)}`)
        }

        await cache?.write({ url, etag: fresh.etag, sha256: hashBytes(fresh.bytes), fetchedAt }, fresh.bytes)
        return { status: { name, url, origin: 'network', fetchedAt }, parsed }
    } catch (error) {
        const failure = message(error)
        const parsed = await readCached()

        return parsed && cached
            ? { status: { name, url, origin: 'cache', fetchedAt: cached.fetchedAt, failure }, parsed }
            : { status: { name, url, origin: 'unavailable', failure } }
    }
}

function offline(assets: SkillAssetStatus[]): SkillsError {
    return {
        code: 'offline',
        message: "Couldn't download the PostHog skills, and the cache folder has no copy of them.",
        assets,
    }
}

// A `learn` command in a skill's text, bare or inside an exec tool call, which a CLI serves as the
// bare command. Only a bare `learn` followed by a learn argument counts, so prose such as "learn more"
// stays as it is. `skills` counts only at the end of a quoted command, because "learn skills" also
// reads as prose.
const LEARN_COMMAND =
    /posthog:exec\(\{\s*"command":\s*"learn((?: (?:\\.|[^"\\])*)?)"\s*\}\)|(?<=^|[\s`"(])learn(?=`| (?:skills(?=[`"]|$)|-s\b|-d\b|--lines\b|posthog:|project:|<))/gm

export function rewriteLearnCommands(text: string, learnCommand: string): string {
    return text.replace(
        LEARN_COMMAND,
        (_match, execArguments: string | undefined) =>
            `${learnCommand}${execArguments === undefined ? '' : execArguments.replace(/\\"/g, '"')}`
    )
}

// The exec tool reads one command string, so each word is quoted to reach its tokenizer intact.
function learnInput(words: readonly string[]): string {
    return words.map((word) => `"${word.replace(/[\\"]/g, '\\$&')}"`).join(' ')
}

function learnWords(skill: string | undefined, paths: readonly string[], request: LearnRequest): string[] {
    const words = skill === undefined ? [...paths] : [skill, ...paths]

    if (request.describe) {
        return ['-d', ...words]
    }
    if (request.lines !== undefined) {
        return [...words, '--lines', request.lines]
    }
    if (request.search !== undefined) {
        return skill === undefined ? ['-s', request.search, ...paths] : [...words, '-s', request.search]
    }
    return words
}

function learnError(error: unknown): SkillsError {
    const code =
        error instanceof SkillsUnavailableError
            ? 'unavailable'
            : error instanceof LearnLookupError
              ? error.code
              : 'usage'

    return { code, message: message(error) }
}

const Listing = z.object({
    posthog: z.object({ skills: z.array(z.string()), count: z.number(), truncated: z.boolean() }),
})

export function createSkillsLibrary(options: SkillsLibraryOptions): SkillsLibrary {
    const settings: Settings = {
        cacheDir: options.cacheDir,
        fetch: options.fetch ?? ((url, init) => fetch(url, init)),
        responseTimeoutMs: options.responseTimeoutMs ?? DEFAULT_RESPONSE_TIMEOUT_MS,
        downloadTimeoutMs: options.downloadTimeoutMs ?? DEFAULT_DOWNLOAD_TIMEOUT_MS,
        now: options.now ?? Date.now,
    }
    const learnCommand = options.learnCommand ?? 'learn'

    const loadContextMill = memoizeWhileFresh(async () => {
        const loaded = await loadAsset(settings, 'context-mill', parseContextMill)
        return { release: loaded.parsed, assets: [loaded.status] }
    })

    const loadProductSkills = memoizeWhileFresh(async () => {
        const loaded = await loadAsset(settings, 'product-skills', (bytes) => SkillCatalog.fromZip(bytes))
        return { catalog: loaded.parsed, assets: [loaded.status] }
    })

    // Each asset keeps its own network copy, so an outage of one doesn't download the other again.
    const loadCatalog = memoizeWhileFresh(async () => {
        const [product, contextMill] = await Promise.all([loadProductSkills(), loadContextMill()])
        const omnibus = contextMill.release?.omnibus()
        const catalog = product.catalog && omnibus ? product.catalog.withOverlay(omnibus) : (product.catalog ?? omnibus)

        return {
            catalog: catalog?.mapText((text) => rewriteLearnCommands(text, learnCommand)),
            assets: [...product.assets, ...contextMill.assets],
        }
    })

    const loadRelease = async (): Promise<SkillsResult<LoadedRelease>> => {
        const { release, assets } = await loadContextMill()
        return release ? { ok: true, value: { release, assets } } : { ok: false, error: offline(assets) }
    }

    // The releases `installable` handed out. A load that fell back to the cache isn't memoized, so
    // without this each install of a batch would wait for the network to fail again.
    const handedOut = new WeakMap<SkillsRelease, ContextMillRelease>()

    const releaseFor = async (handle: SkillsRelease | undefined): Promise<SkillsResult<LoadedRelease>> => {
        const release = handle && handedOut.get(handle)
        return release && handle ? { ok: true, value: { release, assets: handle.assets } } : loadRelease()
    }

    return {
        async learn(request): Promise<SkillsResult<LearnResult>> {
            // The exec tool never sees an empty word, because its tokenizer drops them.
            const skill = request.skill?.trim() ? request.skill : undefined
            const paths = request.paths.filter((word) => word.trim())
            const { search, describe, lines } = request
            const modes = Number(search !== undefined) + Number(describe === true) + Number(lines !== undefined)

            if (modes > 1) {
                return {
                    ok: false,
                    error: { code: 'usage', message: 'Give only one of search, describe and lines.' },
                }
            }

            if (skill === undefined && paths.length === 0 && modes === 0) {
                // The overview lists fixed commands, so it answers without the network.
                const commands = learnSkillCommands(learnCommand).filter((command) => !command.includes('project:'))
                return { ok: true, value: { output: { kind: 'overview', commands }, reads: [], assets: [] } }
            }

            const { catalog, assets } = await loadCatalog()
            if (!catalog) {
                return { ok: false, error: offline(assets) }
            }

            const reads: SkillRead[] = []
            const learn = new ExecLearnCatalog(
                [],
                { posthog: catalog, projectUnavailableReason: PROJECT_SKILLS_UNAVAILABLE },
                ({ source, skill: name, path: file, readKind }) =>
                    reads.push({ source, skill: name, path: file ?? 'SKILL.md', readKind }),
                learnCommand
            )

            try {
                const raw = await learn.execute(learnInput(learnWords(skill, paths, request)))

                if (skill === 'skills' && paths.length === 0 && modes === 0) {
                    const { skills, count, truncated } = Listing.parse(JSON.parse(raw)).posthog
                    return { ok: true, value: { output: { kind: 'list', skills, count, truncated }, reads, assets } }
                }

                return { ok: true, value: { output: { kind: 'text', text: raw }, reads, assets } }
            } catch (error) {
                return { ok: false, error: learnError(error) }
            }
        },

        async installable(): Promise<
            SkillsResult<{ skills: InstallableSkill[]; assets: SkillAssetStatus[]; release: SkillsRelease }>
        > {
            const loaded = await loadRelease()
            if (!loaded.ok) {
                return loaded
            }

            const { release, assets } = loaded.value
            const handle: SkillsRelease = { assets }
            handedOut.set(handle, release)

            return { ok: true, value: { skills: await listSkills(release), assets, release: handle } }
        },

        async instrumentSkills(): Promise<SkillsResult<{ skills: string[]; assets: SkillAssetStatus[] }>> {
            const loaded = await loadRelease()
            if (!loaded.ok) {
                return loaded
            }

            const names = loaded.value.release.omnibus()?.listNames() ?? []

            return {
                ok: true,
                value: {
                    skills: names
                        .filter((name) => name.startsWith(INSTRUMENT_SKILL_PREFIX))
                        .map((name) => `posthog:${name}`),
                    assets: loaded.value.assets,
                },
            }
        },

        async install(id, { cwd, force, skillsDir, release: handle }) {
            const loaded = await releaseFor(handle)
            if (!loaded.ok) {
                return loaded
            }

            const { release, assets } = loaded.value

            try {
                return {
                    ok: true,
                    value: { skill: await installSkill(id, { cwd, force, skillsDir, source: release }), assets },
                }
            } catch (error) {
                return { ok: false, error: installError(id, error) }
            }
        },
    }
}

function installError(id: string, error: unknown): SkillsError {
    if (!(error instanceof SkillInstallError)) {
        return { code: 'install_failed', message: message(error) }
    }

    switch (error.code) {
        case 'unknown_skill':
            // installSkill's own message names posthog-cli's list command, which is not this caller's.
            return { code: 'unknown_skill', message: `Unknown skill "${id}".` }
        case 'invalid_skill_id':
            return { code: 'usage', message: error.message }
        case 'already_installed':
            return { code: 'already_installed', message: error.message }
    }
}
