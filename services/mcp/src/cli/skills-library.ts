import { strFromU8, strToU8, type Unzipped } from 'fflate'
import { randomUUID } from 'node:crypto'
import * as fs from 'node:fs/promises'
import * as path from 'node:path'
import { z } from 'zod'

import { hashBytes } from '@/hono/cache/SharedBlobCache'
import { CONTEXT_MILL_URL, contextMillEntries, omnibusSkillFiles, unzipOmnibusArchives } from '@/resources/internals'
import {
    type LearnCommands,
    learnCommands,
    LearnLookupError,
    makeSkillFile,
    MAX_SKILL_ARCHIVE_BYTES,
    PRODUCT_SKILL_ARCHIVE_URL,
    SkillCatalog,
    type SkillDefinition,
    unzipUntrusted,
} from '@/skills/skill-catalog'

import type {
    CatalogSkill,
    FoundSkill,
    SkillAssetName,
    SkillAssetStatus,
    SkillCommands,
    SkillRead,
    SkillReadRequest,
    SkillReadResult,
    SkillSearchResult,
    SkillsError,
    SkillsFetch,
    SkillsLibrary,
    SkillsLibraryOptions,
    SkillsRelease,
    SkillsResult,
    SkillKind,
} from './library-types'
import { installSkill, type InstallableSkills, SkillInstallError, writeSkill } from './skills'

const DEFAULT_RESPONSE_TIMEOUT_MS = 5_000
const DEFAULT_DOWNLOAD_TIMEOUT_MS = 60_000
const INSTRUMENT_SKILL_PREFIX = 'instrument-'
// context-mill also publishes each omnibus skill as a resource named `omnibus-<name>`. The catalog
// serves it once, as `<name>`, from the omnibus archive.
const OMNIBUS_RESOURCE_PREFIX = 'omnibus-'
const SKILL_NAMESPACE = 'posthog:'
const MAX_SEARCH_LENGTH = 200
const LINE_RANGE = /^([1-9]\d*):([1-9]\d*)$/

// The MCP `learn` command, for a caller that names no commands of its own.
const LEARN_COMMANDS: SkillCommands = {
    read: (skill, file, lines) => learnCommands().read(`${SKILL_NAMESPACE}${skill}`, file, lines),
    search: (keywords) => learnCommands().search(keywords),
    list: 'learn skills',
}

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
    // The resource skills as listings: name and description only. Their files stay zipped until
    // `resourceSkill` reads one, because unzipping every resource on each call would take about a second.
    resourceListings(): SkillDefinition[]
    resourceSkill(id: string): SkillDefinition | undefined
}

interface LoadedRelease {
    release: ContextMillRelease
    assets: SkillAssetStatus[]
}

// The release counts as valid when its manifest loads. Every other file stays zipped until a call
// reads it: a skill's zip to install it, or the omnibus skills for `learn`.
function parseContextMill(bytes: Uint8Array): ContextMillRelease {
    let omnibus: { catalog: SkillCatalog | undefined } | undefined

    const entries = contextMillEntries(bytes)
    const readFile = (name: string): Uint8Array | undefined =>
        unzipUntrusted(bytes, 'The context-mill release', (file) => file.name === name)[name]
    const resources = entries.filter((entry) => entry.file && !entry.id.startsWith(OMNIBUS_RESOURCE_PREFIX))

    return {
        entries,
        readFile,
        omnibus: () => {
            omnibus ??= { catalog: omnibusCatalog(bytes) }
            return omnibus.catalog
        },
        resourceListings: () =>
            resources.map((entry) => {
                const description =
                    typeof entry.description === 'string' ? entry.description : entry.resource.description
                return {
                    name: entry.id,
                    description,
                    files: [makeSkillFile('SKILL.md', `# ${entry.name}\n\n${description}\n`)],
                }
            }),
        resourceSkill: (id) => {
            const entry = resources.find((candidate) => candidate.id === id)
            const zipped = entry?.file ? readFile(entry.file) : undefined
            return zipped ? resourceSkill(id, unzipUntrusted(zipped, `Skill archive "${entry?.file}"`)) : undefined
        },
    }
}

// `learn` serves text only, so a binary file in a resource skill is left out of what it reads.
// `install` writes the resource's own archive, binary files included.
function resourceSkill(id: string, files: Unzipped): SkillDefinition | undefined {
    const text: Unzipped = Object.fromEntries(
        Object.entries(files)
            .filter(([file, bytes]) => !file.endsWith('/') && !strFromU8(bytes).includes('\0'))
            .map(([file, bytes]) => [`${id}/${file}`, bytes])
    )

    try {
        return SkillCatalog.fromFiles(text).get(id)
    } catch {
        return undefined
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

// A `learn` command in a skill's text, in backticks or inside an exec tool call. Prose such as "learn more"
// has no backticks, so it stays as it is.
const LEARN_COMMAND = /`learn((?: [^`]*)?)`|posthog:exec\(\{\s*"command":\s*"learn((?: (?:\\.|[^"\\])*)?)"\s*\}\)/g

function learnWords(text: string): string[] {
    return [...text.matchAll(/"([^"]*)"|(\S+)/g)].map((match) => match[1] ?? match[2]!)
}

// The caller's commands for one `learn` command, or undefined when the caller has none for it. A batch
// becomes one read each, and a search of one file becomes a read of the file.
function translateLearn(words: readonly string[], commands: SkillCommands): string[] | undefined {
    const [first, ...rest] = words
    if (first === undefined || first === 'skills' || first === '-d') {
        return [commands.list]
    }
    if (first === '-s') {
        return [commands.search(rest.join(' '))]
    }

    const skill = /^(?:posthog|<source>):(.+)$/.exec(first)?.[1]
    if (skill === undefined) {
        return undefined
    }
    if (rest.length > 0 && rest.every((word) => word.startsWith(SKILL_NAMESPACE))) {
        return [skill, ...rest.map(bareName)].map((name) => commands.read(name))
    }

    const flag = rest.findIndex((word) => word.startsWith('-'))
    const files = flag === -1 ? rest : rest.slice(0, flag)
    const lines = rest[flag] === '--lines' ? rest[flag + 1] : undefined
    if (files.length === 0) {
        return [commands.read(skill)]
    }
    return files.map((file) => commands.read(skill, file, files.length === 1 ? lines : undefined))
}

export function rewriteLearnCommands(text: string, commands: SkillCommands): string {
    return text.replace(LEARN_COMMAND, (match, quoted: string | undefined, exec: string | undefined) => {
        const words = learnWords(quoted ?? exec?.replace(/\\"/g, '"') ?? '')
        const translated = translateLearn(words, commands)
        if (!translated) {
            return match
        }
        return quoted === undefined
            ? translated.join(' and ')
            : translated.map((command) => `\`${command}\``).join(' and ')
    })
}

function readError(error: unknown): SkillsError {
    const code = error instanceof LearnLookupError && error.code !== 'unknown_topic' ? error.code : 'usage'
    return { code, message: message(error) }
}

interface Catalog {
    catalog: SkillCatalog
    kinds: ReadonlyMap<string, SkillKind>
    // The names listed from context-mill resources, whose files `withFiles` loads on demand.
    resources: ReadonlySet<string>
    release: ContextMillRelease | undefined
}

interface LoadedCatalog {
    loaded: Catalog | undefined
    assets: SkillAssetStatus[]
}

// Every skill once, by name. A product skill wins over a context-mill skill of the same name, because
// the product archive can be sha-pinned and context-mill is not.
function combineSkills(
    product: SkillCatalog | undefined,
    release: ContextMillRelease | undefined
): Catalog | undefined {
    const kinds = new Map<string, SkillKind>()
    const resources = new Set<string>()
    const definitions: SkillDefinition[] = []
    const add = (skill: SkillDefinition | undefined, kind: SkillKind): boolean => {
        if (!skill || kinds.has(skill.name)) {
            return false
        }

        kinds.set(skill.name, kind)
        definitions.push(skill)
        return true
    }

    const omnibus = release?.omnibus()
    for (const name of product?.listNames() ?? []) {
        add(product?.get(name), omnibus?.has(name) ? 'implementation' : 'learning')
    }
    for (const name of omnibus?.listNames() ?? []) {
        add(omnibus?.get(name), 'implementation')
    }
    for (const listing of release?.resourceListings() ?? []) {
        if (add(listing, 'implementation')) {
            resources.add(listing.name)
        }
    }

    return definitions.length > 0 ? { catalog: new SkillCatalog(definitions), kinds, resources, release } : undefined
}

function bareName(name: string): string {
    return name.startsWith(SKILL_NAMESPACE) ? name.slice(SKILL_NAMESPACE.length) : name
}

function catalogSkills({ catalog, kinds }: Catalog): CatalogSkill[] {
    const skills = catalog.listNames().map((name) => ({
        name,
        kind: kinds.get(name) ?? 'implementation',
        description: (catalog.describe(name) ?? '').trim().split('\n')[0] ?? '',
    }))
    const order: Record<SkillKind, number> = { learning: 0, implementation: 1 }

    return skills.sort((left, right) => order[left.kind] - order[right.kind] || left.name.localeCompare(right.name))
}

export function createSkillsLibrary(options: SkillsLibraryOptions): SkillsLibrary {
    const settings: Settings = {
        cacheDir: options.cacheDir,
        fetch: options.fetch ?? ((url, init) => fetch(url, init)),
        responseTimeoutMs: options.responseTimeoutMs ?? DEFAULT_RESPONSE_TIMEOUT_MS,
        downloadTimeoutMs: options.downloadTimeoutMs ?? DEFAULT_DOWNLOAD_TIMEOUT_MS,
        now: options.now ?? Date.now,
    }
    const commands = options.commands ?? LEARN_COMMANDS
    const rewrite = (text: string): string => rewriteLearnCommands(text, commands)
    // Hints in served text, such as how to read a file, name the caller's commands. The skill name is bare.
    const catalogCommands: LearnCommands = { read: commands.read, search: commands.search }

    const loadContextMill = memoizeWhileFresh(async () => {
        const loaded = await loadAsset(settings, 'context-mill', parseContextMill)
        return { release: loaded.parsed, assets: [loaded.status] }
    })

    const loadProductSkills = memoizeWhileFresh(async () => {
        const loaded = await loadAsset(settings, 'product-skills', (bytes) => SkillCatalog.fromZip(bytes))
        return { catalog: loaded.parsed, assets: [loaded.status] }
    })

    // Each asset keeps its own network copy, so an outage of one doesn't download the other again.
    const loadCatalog = memoizeWhileFresh(async (): Promise<LoadedCatalog> => {
        const [product, contextMill] = await Promise.all([loadProductSkills(), loadContextMill()])
        const combined = combineSkills(product.catalog, contextMill.release)

        return {
            loaded: combined && { ...combined, catalog: combined.catalog.mapText(rewrite) },
            assets: [...product.assets, ...contextMill.assets],
        }
    })

    const loadRelease = async (): Promise<SkillsResult<LoadedRelease>> => {
        const { release, assets } = await loadContextMill()
        return release ? { ok: true, value: { release, assets } } : { ok: false, error: offline(assets) }
    }

    // A resource skill is listed by name and description only. A read of one gets a catalog with its files
    // in place of its listing. A skill whose archive can't be read fails the read, because serving its
    // listing would count as a read of the skill.
    const withFiles = ({ catalog, resources, release }: Catalog, id: string): SkillsResult<SkillCatalog> => {
        if (!resources.has(id)) {
            return { ok: true, value: catalog }
        }

        const skill = release?.resourceSkill(id)
        if (!skill) {
            return {
                ok: false,
                error: {
                    code: 'unavailable',
                    message: `Couldn't read the skill "${id}", because its archive in the skills release has no valid SKILL.md.`,
                },
            }
        }

        const loaded = new SkillCatalog([skill]).mapText(rewrite)
        return {
            ok: true,
            value: new SkillCatalog(catalog.listNames().map((other) => loaded.get(other) ?? catalog.get(other)!)),
        }
    }

    // The catalogs `catalog` handed out, so each install of a batch writes from the same download.
    const handedOut = new WeakMap<SkillsRelease, LoadedCatalog>()

    return {
        async read({ skill, file, lines }: SkillReadRequest): Promise<SkillsResult<SkillReadResult>> {
            const range = lines === undefined ? undefined : LINE_RANGE.exec(lines)
            if (range === null) {
                return {
                    ok: false,
                    error: { code: 'usage', message: 'Give the lines as `<start>:<end>`, such as `10:40`.' },
                }
            }

            const { loaded, assets } = await loadCatalog()
            if (!loaded) {
                return { ok: false, error: offline(assets) }
            }

            const id = bareName(skill.trim())
            if (!loaded.catalog.has(id)) {
                return { ok: false, error: { code: 'unknown_skill', message: `Unknown skill "${skill}".` } }
            }

            const catalog = withFiles(loaded, id)
            if (!catalog.ok) {
                return catalog
            }

            try {
                const text = range
                    ? catalog.value.readLines(
                          id,
                          file ?? 'SKILL.md',
                          Number(range[1]),
                          Number(range[2]),
                          id,
                          catalogCommands
                      )
                    : catalog.value.read(id, file, id, catalogCommands)
                const read: SkillRead = {
                    source: 'posthog',
                    skill: id,
                    path: file ?? 'SKILL.md',
                    readKind: range ? 'file_lines' : file === undefined ? 'skill' : 'file',
                }
                return { ok: true, value: { text, reads: [read], assets } }
            } catch (error) {
                return { ok: false, error: readError(error) }
            }
        },

        async search(keywords): Promise<SkillsResult<SkillSearchResult>> {
            const query = keywords.trim()
            if (!query || query.length > MAX_SEARCH_LENGTH) {
                return {
                    ok: false,
                    error: {
                        code: 'usage',
                        message: `Give between 1 and ${MAX_SEARCH_LENGTH} characters of keywords.`,
                    },
                }
            }

            const { loaded, assets } = await loadCatalog()
            if (!loaded) {
                return { ok: false, error: offline(assets) }
            }

            const skills: FoundSkill[] = loaded.catalog.searchResults(query).map((result) => ({
                name: result.identifier,
                description: result.description,
                matches: result.snippets.map(({ path: file, line, text }) => ({ path: file, line, text })),
            }))
            return { ok: true, value: { skills, assets } }
        },

        async catalog() {
            const loaded = await loadCatalog()
            if (!loaded.loaded) {
                return { ok: false, error: offline(loaded.assets) }
            }

            const handle: SkillsRelease = { assets: loaded.assets }
            handedOut.set(handle, loaded)

            return { ok: true, value: { skills: catalogSkills(loaded.loaded), assets: loaded.assets, release: handle } }
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
                        .map((name) => `${SKILL_NAMESPACE}${name}`),
                    assets: loaded.value.assets,
                },
            }
        },

        async install(name, { cwd, force, skillsDir, release: handle }) {
            const { loaded, assets } = (handle && handedOut.get(handle)) || (await loadCatalog())
            if (!loaded) {
                return { ok: false, error: offline(assets) }
            }

            const id = bareName(name)
            const options = { cwd, force, skillsDir }

            try {
                const skill = loaded.catalog.get(id)
                if (!skill) {
                    return { ok: false, error: { code: 'unknown_skill', message: `Unknown skill "${name}".` } }
                }

                // A resource skill is written from its own archive. Every other skill is written from
                // the files `learn` serves, so the installed copy names commands the way `learn` does.
                const installed =
                    loaded.release && loaded.resources.has(id)
                        ? await installSkill(id, { ...options, source: loaded.release })
                        : await writeSkill(
                              id,
                              Object.fromEntries(skill.files.map((file) => [file.path, strToU8(file.content)])),
                              options
                          )

                return { ok: true, value: { skill: installed, assets } }
            } catch (error) {
                return { ok: false, error: installError(name, error) }
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
