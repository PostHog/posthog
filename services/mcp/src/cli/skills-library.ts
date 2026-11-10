// PostHog's agent skills with the `learn` grammar of the MCP server's exec tool, for CLIs that serve
// them in-process. `scripts/build-cli-library.ts` bundles this file on its own, so a CLI loads it
// without the tool catalog.
import { unzipSync } from 'fflate'
import { randomUUID } from 'node:crypto'
import * as fs from 'node:fs/promises'
import * as path from 'node:path'
import { z } from 'zod'

import { hashBytes } from '@/hono/cache/SharedBlobCache'
import { CONTEXT_MILL_URL, extractContextMill } from '@/resources/internals'
import { PRODUCT_SKILL_ARCHIVE_URL, SkillCatalog } from '@/skills/skill-catalog'
import { ExecLearnCatalog, SkillsUnavailableError } from '@/tools/exec-learn'

import type {
    InstallableSkill,
    LearnOutput,
    LearnResult,
    SkillAssetName,
    SkillAssetStatus,
    SkillRead,
    SkillsError,
    SkillsFetch,
    SkillsLibrary,
    SkillsLibraryOptions,
    SkillsResult,
} from './library-types'
import { installSkill, type InstallableSkills, listSkills } from './skills'
import { replaceExecInvocations } from './utils'

const DEFAULT_RESPONSE_TIMEOUT_MS = 5_000
const DEFAULT_DOWNLOAD_TIMEOUT_MS = 60_000
const MAX_ASSET_BYTES = 64 * 1024 * 1024
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
function keepOnline<T extends { assets: readonly SkillAssetStatus[] }>(load: () => Promise<T>): () => Promise<T> {
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

// The release counts as valid when its manifest loads. The omnibus skills are read only for `learn`.
function parseContextMill(bytes: Uint8Array): InstallableSkills {
    const archive = unzipSync(bytes)
    return { archive, entries: extractContextMill(archive, false).entries }
}

// Omnibus skills that don't parse are left out, as the server leaves them out.
function omnibusCatalog(release: InstallableSkills): SkillCatalog | undefined {
    try {
        const { omnibusSkillsArchive } = extractContextMill(release.archive)
        return omnibusSkillsArchive ? SkillCatalog.fromZip(omnibusSkillsArchive) : undefined
    } catch {
        return undefined
    }
}

// A copy in the cache folder, written by an earlier load. Each copy's file is named by its hash and
// the record points to it, so a write that stops halfway, or two runs that write at once, never leave
// a record without its copy.
class AssetCache {
    constructor(
        private readonly folder: string | undefined,
        private readonly name: SkillAssetName
    ) {}

    private file(suffix: string): string | undefined {
        return this.folder && path.join(this.folder, `${this.name}${suffix}`)
    }

    private bytesFile(record: CacheRecord): string | undefined {
        return this.file(`-${record.sha256.slice(0, 16)}.zip`)
    }

    async record(): Promise<CacheRecord | undefined> {
        const file = this.file('.json')
        try {
            const parsed = file && CacheRecord.safeParse(JSON.parse(await fs.readFile(file, 'utf8')))
            return parsed && parsed.success ? parsed.data : undefined
        } catch {
            return undefined
        }
    }

    async bytes(record: CacheRecord): Promise<Uint8Array | undefined> {
        const file = this.bytesFile(record)
        try {
            const bytes = file && (await fs.readFile(file))
            return bytes && hashBytes(bytes) === record.sha256 ? bytes : undefined
        } catch {
            return undefined
        }
    }

    // A cache that can't be written only costs the next offline run its fallback.
    async write(record: CacheRecord, bytes?: Uint8Array, previous?: CacheRecord): Promise<void> {
        const [bytesFile, recordFile] = [this.bytesFile(record), this.file('.json')]
        if (!this.folder || !bytesFile || !recordFile) {
            return
        }
        try {
            await fs.mkdir(this.folder, { recursive: true })
            if (bytes) {
                await writeAtomically(bytesFile, bytes)
            }
            await writeAtomically(recordFile, JSON.stringify(record))
            const stale = previous && previous.sha256 !== record.sha256 ? this.bytesFile(previous) : undefined
            if (stale) {
                await fs.rm(stale, { force: true })
            }
        } catch {
            return
        }
    }
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
    try {
        const response = await settings.fetch(url, {
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
        if (Number.isFinite(length) && length > MAX_ASSET_BYTES) {
            throw new DownloadError(`The asset is ${length} bytes, over the ${MAX_ASSET_BYTES} byte limit`)
        }
        const bytes = new Uint8Array(await response.arrayBuffer())
        if (bytes.length === 0 || bytes.length > MAX_ASSET_BYTES) {
            throw new DownloadError(`The asset is ${bytes.length} bytes`)
        }
        // GitHub redirects release assets to storage, and the final response carries the asset's own ETag.
        return { bytes, etag: response.headers.get('etag') ?? undefined }
    } catch (error) {
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
    const cache = new AssetCache(settings.cacheDir, name)
    const record = await cache.record()
    const cached = record?.url === url ? record : undefined
    const readCached = async (): Promise<T | undefined> => {
        const bytes = cached && (await cache.bytes(cached))
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
                await cache.write({ ...cached, fetchedAt })
                return { status: { name, url, origin: 'network', fetchedAt }, parsed }
            }
            // The record's copy is gone, so the 304 can't be served. Ask again for the whole asset.
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
        await cache.write({ url, etag: fresh.etag, sha256: hashBytes(fresh.bytes), fetchedAt }, fresh.bytes, record)
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

// Rewrites `learn ...` in text the catalog wrote, and in skill files, into the caller's syntax. Only a
// `learn` followed by a learn argument counts, so prose such as "learn more" stays as it is. `skills`
// counts only at the end of a quoted command, because "learn skills" also reads as prose.
const LEARN_COMMAND = /(?<=^|[\s`"(])learn(?=`| (?:skills(?=[`"]|$)|-s\b|-d\b|--lines\b|posthog:|project:|<))/gm

export function rewriteLearnCommands(text: string, learnCommand: string): string {
    if (learnCommand === 'learn') {
        return text
    }
    // A `learn` that already follows the caller's prefix, as in `hog learn`, is in the caller's syntax.
    const prefix = learnCommand.endsWith('learn') ? learnCommand.slice(0, -'learn'.length) : undefined
    const rewritten = text.replace(LEARN_COMMAND, (match, offset: number) =>
        prefix && text.slice(Math.max(0, offset - prefix.length), offset) === prefix ? match : learnCommand
    )
    // The regex also rewrites the command inside an exec tool call, which then becomes the bare command.
    return replaceExecInvocations(rewritten, (command) =>
        command === 'learn' ? learnCommand : command.startsWith(`${learnCommand} `) ? command : undefined
    )
}

// The exec tool reads one command string, so each word is quoted to reach its tokenizer intact.
function learnInput(words: readonly string[]): string {
    return words.map((word) => `"${word.replace(/[\\"]/g, '\\$&')}"`).join(' ')
}

// The catalog throws plain errors, which the MCP server also classifies by how their message starts.
const LEARN_ERROR_CODES: readonly [prefix: string, code: SkillsError['code']][] = [
    ['Unknown skill:', 'unknown_skill'],
    ['Unknown file:', 'unknown_file'],
    ['Unknown ', 'unknown_topic'],
]

function learnError(error: unknown, learnCommand: string): SkillsError {
    const raw = message(error)
    const code =
        error instanceof SkillsUnavailableError
            ? 'unavailable'
            : (LEARN_ERROR_CODES.find(([prefix]) => raw.startsWith(prefix))?.[1] ?? 'usage')
    return { code, message: rewriteLearnCommands(raw, learnCommand) }
}

const Overview = z.object({ skills: z.object({ commands: z.array(z.string()) }) })
const Listing = z.object({
    posthog: z.object({ skills: z.array(z.string()), count: z.number(), truncated: z.boolean() }),
})

function learnOutput(words: readonly string[], raw: string, learnCommand: string): LearnOutput {
    if (words.length === 0) {
        const { commands } = Overview.parse(JSON.parse(raw)).skills
        return {
            kind: 'overview',
            commands: commands
                .filter((command) => !command.includes('project:'))
                .map((command) => command.replace(/^learn\b/, learnCommand)),
        }
    }
    if (words.length === 1 && words[0] === 'skills') {
        const { skills, count, truncated } = Listing.parse(JSON.parse(raw)).posthog
        return { kind: 'list', skills, count, truncated }
    }
    return { kind: 'text', text: rewriteLearnCommands(raw, learnCommand) }
}

export function createSkillsLibrary(options: SkillsLibraryOptions): SkillsLibrary {
    const settings: Settings = {
        cacheDir: options.cacheDir,
        fetch: options.fetch ?? ((url, init) => fetch(url, init)),
        responseTimeoutMs: options.responseTimeoutMs ?? DEFAULT_RESPONSE_TIMEOUT_MS,
        downloadTimeoutMs: options.downloadTimeoutMs ?? DEFAULT_DOWNLOAD_TIMEOUT_MS,
        now: options.now ?? Date.now,
    }
    const learnCommand = options.learnCommand ?? 'learn'
    const loadContextMill = keepOnline(async () => {
        const loaded = await loadAsset(settings, 'context-mill', parseContextMill)
        return { ...loaded, assets: [loaded.status] }
    })
    const loadCatalog = keepOnline(async () => {
        const [product, contextMill] = await Promise.all([
            loadAsset(settings, 'product-skills', (bytes) => SkillCatalog.fromZip(bytes)),
            loadContextMill(),
        ])
        const omnibus = contextMill.parsed && omnibusCatalog(contextMill.parsed)
        return {
            catalog: product.parsed && omnibus ? product.parsed.withOverlay(omnibus) : (product.parsed ?? omnibus),
            assets: [product.status, contextMill.status],
        }
    })
    const loadInstallable = async (): Promise<
        SkillsResult<{ skills: InstallableSkills; assets: SkillAssetStatus[] }>
    > => {
        const { parsed, assets } = await loadContextMill()
        return parsed ? { ok: true, value: { skills: parsed, assets } } : { ok: false, error: offline(assets) }
    }

    return {
        async learn(given): Promise<SkillsResult<LearnResult>> {
            // The exec tool never sees an empty word, because its tokenizer drops them.
            const words = given.filter((word) => word.trim())
            // The overview lists fixed commands, so it answers without the network.
            const { catalog, assets } = words.length === 0 ? { catalog: undefined, assets: [] } : await loadCatalog()
            if (!catalog && words.length > 0) {
                return { ok: false, error: offline(assets) }
            }
            const reads: SkillRead[] = []
            const learn = new ExecLearnCatalog(
                [],
                { posthog: catalog, projectUnavailableReason: PROJECT_SKILLS_UNAVAILABLE },
                ({ source, skill, path: file, readKind }) =>
                    reads.push({ source, skill, path: file ?? 'SKILL.md', readKind })
            )
            try {
                const raw = await learn.execute(learnInput(words))
                return { ok: true, value: { output: learnOutput(words, raw, learnCommand), reads, assets } }
            } catch (error) {
                return { ok: false, error: learnError(error, learnCommand) }
            }
        },

        async installable(): Promise<SkillsResult<{ skills: InstallableSkill[]; assets: SkillAssetStatus[] }>> {
            const loaded = await loadInstallable()
            if (!loaded.ok) {
                return loaded
            }
            return { ok: true, value: { skills: await listSkills(loaded.value.skills), assets: loaded.value.assets } }
        },

        async install(id, { cwd, force }) {
            const loaded = await loadInstallable()
            if (!loaded.ok) {
                return loaded
            }
            const { skills, assets } = loaded.value
            // installSkill's own message names posthog-cli's list command, which is not this caller's.
            if (!skills.entries.some((entry) => entry.id === id)) {
                return { ok: false, error: { code: 'unknown_skill', message: `Unknown skill "${id}".` } }
            }
            try {
                return { ok: true, value: { skill: await installSkill(id, { cwd, force, source: skills }), assets } }
            } catch (error) {
                const text = message(error)
                const code = text.includes('is already installed')
                    ? 'already_installed'
                    : text.startsWith('Invalid skill ID')
                      ? 'usage'
                      : 'install_failed'
                return { ok: false, error: { code, message: text } }
            }
        },
    }
}
