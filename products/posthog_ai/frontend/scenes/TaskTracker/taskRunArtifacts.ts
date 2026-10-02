import { combineUrl } from 'kea-router'

import type {
    TaskRunArtifactResponseApi,
    TaskRunLivingArtifactResponseApi,
    TaskRunLivingArtifactsResponseApi,
} from 'products/tasks/frontend/generated/api.schemas'

export type TaskRunTab = 'conversation' | 'artifacts'

// pinned: URL search params. Shared links and the space feed's file chips use them.
// A link opens the tab on one file, and on one version when it is not the latest.
export const ARTIFACT_PARAM = 'artifact'
export const VERSION_PARAM = 'artifact_version'

/** The path that opens a task's Artifacts tab on one file. `fileKey` is an `ArtifactFile` key. */
export function taskArtifactPath(taskId: string, fileKey: string, versionId?: string | null): string {
    const params: Record<string, string> = { task: taskId, [ARTIFACT_PARAM]: fileKey }
    if (versionId) {
        params[VERSION_PARAM] = versionId
    }
    return combineUrl('/ai', params).url
}

export type ArtifactPreviewKind = 'markdown' | 'html' | 'image' | 'video' | 'csv' | 'text' | 'reference' | 'none'

export const ARTIFACT_KIND_LABEL: Record<ArtifactPreviewKind, string> = {
    markdown: 'Markdown',
    html: 'HTML',
    image: 'Image',
    video: 'Video',
    csv: 'CSV',
    text: 'Text',
    reference: 'PostHog object',
    none: 'File',
}

const TEXT_EXTENSIONS = ['txt', 'json', 'log', 'yaml', 'yml', 'xml', 'sql', 'py', 'ts', 'tsx', 'js', 'sh']

function extension(name: string): string {
    const dot = name.lastIndexOf('.')
    return dot === -1 ? '' : name.slice(dot + 1).toLowerCase()
}

/** The PostHog object a reference artifact points at. Agent messages cite objects, and the run lists each one once. */
export interface PostHogObjectRef {
    objectKind: string
    objectId: string
}

/** Object kinds the preview shows live, with the components their own pages use. Others show a card. */
export const LIVE_OBJECT_KINDS: ReadonlySet<string> = new Set(['insight', 'hogql', 'dashboard', 'replay'])

export function postHogObjectRef(artifact: TaskRunArtifactResponseApi): PostHogObjectRef | null {
    const metadata = artifact.metadata
    if (artifact.type !== 'reference' || !metadata || !('reference_type' in metadata)) {
        return null
    }
    if (metadata.reference_type !== 'posthog_object' || !metadata.object_kind || !metadata.object_id) {
        return null
    }
    return { objectKind: metadata.object_kind, objectId: metadata.object_id }
}

export function artifactPreviewKind(
    artifact: TaskRunArtifactResponseApi & { living?: LivingVersion }
): ArtifactPreviewKind {
    if (artifact.living && artifact.living.text === null) {
        return 'none'
    }
    if (artifact.type === 'reference') {
        return 'reference'
    }
    const contentType = (artifact.content_type ?? '').split(';')[0].trim().toLowerCase()
    const ext = extension(artifact.name)
    if (contentType === 'text/html' || ext === 'html' || ext === 'htm') {
        return 'html'
    }
    if (contentType.startsWith('image/') || ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext)) {
        return 'image'
    }
    if (contentType.startsWith('video/') || ['mp4', 'm4v', 'mov', 'webm', 'ogv'].includes(ext)) {
        return 'video'
    }
    if (contentType === 'text/csv' || ext === 'csv') {
        return 'csv'
    }
    if (contentType === 'text/markdown' || ext === 'md' || ext === 'markdown') {
        return 'markdown'
    }
    if (contentType.startsWith('text/') || contentType === 'application/json' || TEXT_EXTENSIONS.includes(ext)) {
        return 'text'
    }
    return 'none'
}

/** A cited object with no live embed shows only a card, so it gets no full page view. */
export function hasFullPageView(artifact: TaskRunArtifactResponseApi & { living?: LivingVersion }): boolean {
    const ref = postHogObjectRef(artifact)
    return ref ? LIVE_OBJECT_KINDS.has(ref.objectKind) : artifactPreviewKind(artifact) !== 'reference'
}

export function isTextPreview(kind: ArtifactPreviewKind): boolean {
    return kind === 'markdown' || kind === 'html' || kind === 'csv' || kind === 'text'
}

/**
 * Files the agent wrote for the user, and the PostHog objects the run cites.
 * Attachments, plans, skill bundles and dismissed entries stay out.
 */
export function visibleRunArtifacts(artifacts: readonly TaskRunArtifactResponseApi[]): TaskRunArtifactResponseApi[] {
    return artifacts.filter((artifact) => {
        if (!artifact.id || artifact.dismissed_at) {
            return false
        }
        if (postHogObjectRef(artifact)) {
            return true
        }
        return (
            !!artifact.storage_path &&
            (artifact.type === 'output' || artifact.type === 'artifact') &&
            artifact.source === 'agent_output'
        )
    })
}

export function formatArtifactSize(bytes = 0): string {
    return bytes < 1024 * 1024
        ? `${Math.max(1, Math.round(bytes / 1024))} KB`
        : `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

/** RFC 4180 CSV: quoted fields may hold commas, newlines and doubled quotes. */
export function parseCsv(text: string): string[][] {
    const rows: string[][] = []
    let row: string[] = []
    let field = ''
    let quoted = false
    for (let i = 0; i < text.length; i++) {
        const char = text[i]
        if (quoted) {
            if (char === '"' && text[i + 1] === '"') {
                field += '"'
                i++
            } else if (char === '"') {
                quoted = false
            } else {
                field += char
            }
        } else if (char === '"') {
            quoted = true
        } else if (char === ',') {
            row.push(field)
            field = ''
        } else if (char === '\n' || char === '\r') {
            if (char === '\r' && text[i + 1] === '\n') {
                i++
            }
            row.push(field)
            rows.push(row)
            row = []
            field = ''
        } else {
            field += char
        }
    }
    if (field !== '' || row.length > 0) {
        row.push(field)
        rows.push(row)
    }
    return rows.filter((cells) => cells.some((cell) => cell !== ''))
}

/**
 * The option a listbox key moves to, or null for a key the list does not handle.
 * The arrows stop at the ends and do not wrap, as in the WAI-ARIA listbox pattern.
 */
export function listboxKeyTarget(key: string, current: number, count: number): number | null {
    if (count === 0) {
        return null
    }
    switch (key) {
        case 'ArrowUp':
            return Math.max(0, current - 1)
        case 'ArrowDown':
            return Math.min(count - 1, current + 1)
        case 'Home':
            return 0
        case 'End':
            return count - 1
        default:
            return null
    }
}

/** A file the agent wrote, with the run that holds it. Downloads must name that run, not the open one. */
export interface RunArtifact extends TaskRunArtifactResponseApi {
    runId: string
    /** Set on a version of a living document. Absent for uploaded files and cited objects. */
    living?: LivingVersion
}

interface RunWithArtifacts {
    id: string
    artifacts?: readonly TaskRunArtifactResponseApi[] | null
}

/**
 * Agent files from every run of a task. A resumed task keeps writing new runs, so the files from earlier
 * runs in the chain are only on those runs. The first run that lists an id wins, so pass the live run first.
 * `dismissals` maps an artifact id to the dismissed state this page last set. It wins over the run data,
 * because the runs can hold a manifest from before that change.
 */
export function collectRunArtifacts(
    runs: readonly (RunWithArtifacts | null | undefined)[],
    dismissals: Readonly<Record<string, boolean>> = {}
): RunArtifact[] {
    const byId = new Map<string, RunArtifact>()
    for (const run of runs) {
        if (!run) {
            continue
        }
        const manifest = (run.artifacts ?? []).map((artifact) => {
            if (!artifact.id || dismissals[artifact.id] !== false) {
                return artifact
            }
            const { dismissed_at: _dismissedAt, ...restored } = artifact
            return restored
        })
        for (const artifact of visibleRunArtifacts(manifest)) {
            if (artifact.id && !dismissals[artifact.id] && !byId.has(artifact.id)) {
                byId.set(artifact.id, { ...artifact, runId: run.id })
            }
        }
    }
    return [...byId.values()].sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))
}

/** One file name with every upload of it, or one cited PostHog object. */
export interface ArtifactFile {
    /** Selects the entry and goes in the share link. The file name, or the artifact id for a reference. */
    key: string
    name: string
    /** Newest first. */
    versions: RunArtifact[]
    latest: RunArtifact
}

/**
 * The agent writes a new artifact each time it saves a file, so each upload of a name is a version of that file.
 * Versions can sit on different runs of the resume chain.
 */
export function groupArtifactVersions(artifacts: readonly RunArtifact[]): ArtifactFile[] {
    const byKey = new Map<string, RunArtifact[]>()
    for (const artifact of artifacts) {
        // Two cited objects can share a name, so a reference keeps its own entry.
        const key = artifact.type === 'reference' && artifact.id ? artifact.id : artifact.name
        const versions = byKey.get(key)
        if (versions) {
            versions.push(artifact)
        } else {
            byKey.set(key, [artifact])
        }
    }
    return [...byKey]
        .map(([key, versions]) => {
            const sorted = [...versions].sort((a, b) => b.uploaded_at.localeCompare(a.uploaded_at))
            return { key, name: sorted[0].name, versions: sorted, latest: sorted[0] }
        })
        .sort(
            (a, b) =>
                // Files first, then cited objects, so the file list and the stepper share one order.
                Number(a.latest.type === 'reference') - Number(b.latest.type === 'reference') ||
                b.latest.uploaded_at.localeCompare(a.latest.uploaded_at)
        )
}

/** One version of a document the agent edits in place, such as a Slack canvas. */
export interface LivingVersion {
    /** The living artifact id. All versions of one document share it. */
    artifactId: string
    adapter: string
    /** `null` when PostHog keeps no text for the version, for example a file sent to Slack. */
    text: string | null
}

export const LIVING_ADAPTER_LABEL: Record<string, string> = {
    slack_message: 'Slack message',
    slack_canvas: 'Slack canvas',
    slack_file: 'Slack file',
    document_connector: 'Document',
    github_pr: 'Pull request',
}

/**
 * The generated client types the list response as an array of envelopes, but the endpoint returns one
 * envelope. Both shapes are read so the list keeps working after the schema is fixed.
 */
export function livingArtifactsFromResponse(
    response: TaskRunLivingArtifactsResponseApi | readonly TaskRunLivingArtifactsResponseApi[] | null | undefined
): TaskRunLivingArtifactResponseApi[] {
    const envelopes: readonly TaskRunLivingArtifactsResponseApi[] = Array.isArray(response)
        ? response
        : response
          ? [response as TaskRunLivingArtifactsResponseApi]
          : []
    const byId = new Map<string, TaskRunLivingArtifactResponseApi>()
    for (const artifact of envelopes.flatMap((envelope) => envelope.artifacts ?? [])) {
        if (artifact.id && !byId.has(artifact.id)) {
            byId.set(artifact.id, artifact)
        }
    }
    return [...byId.values()]
}

function stringField(record: Record<string, unknown>, field: string): string | undefined {
    const value = record[field]
    return typeof value === 'string' && value ? value : undefined
}

/** The registry types each version record as an open object, so every field is checked before use. */
function livingVersionArtifact(
    artifact: TaskRunLivingArtifactResponseApi,
    record: Record<string, unknown>,
    versionNumber: number
): RunArtifact {
    return {
        // The prefix keeps a document apart from an uploaded file or a cited object in `?artifact=`.
        id: `living-${artifact.id}-v${versionNumber}`,
        name: artifact.name,
        type: 'living',
        content_type: stringField(record, 'content_type'),
        size: typeof record.size === 'number' ? record.size : undefined,
        uploaded_at: stringField(record, 'created_at') ?? artifact.updated_at ?? artifact.created_at ?? '',
        runId: stringField(record, 'run_id') ?? artifact.run_id,
        living: {
            artifactId: artifact.id,
            adapter: artifact.adapter,
            text: typeof record.content === 'string' ? record.content : null,
        },
    }
}

/** One entry per living document, with its versions newest first. */
export function livingArtifactFiles(artifacts: readonly TaskRunLivingArtifactResponseApi[]): ArtifactFile[] {
    return artifacts
        .map((artifact) => {
            const records = artifact.versions.length > 0 ? artifact.versions : [{}]
            const versions = records
                .map((record, index) => ({
                    record,
                    number: typeof record.version === 'number' ? record.version : index + 1,
                }))
                .sort((a, b) => b.number - a.number)
                .map(({ record, number }) => livingVersionArtifact(artifact, record, number))
            return { key: `living-${artifact.id}`, name: artifact.name, versions, latest: versions[0] }
        })
        .sort((a, b) => b.latest.uploaded_at.localeCompare(a.latest.uploaded_at))
}
