import type { TaskRunArtifactResponseApi } from 'products/tasks/frontend/generated/api.schemas'

export type TaskRunTab = 'conversation' | 'artifacts'

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
export const LIVE_OBJECT_KINDS: ReadonlySet<string> = new Set([
    'insight',
    'hogql',
    'dashboard',
    'replay',
    'flag',
    'cohort',
])

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

export function artifactPreviewKind(artifact: TaskRunArtifactResponseApi): ArtifactPreviewKind {
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

/** A file the agent wrote, with the run that holds it. Downloads must name that run, not the open one. */
export interface RunArtifact extends TaskRunArtifactResponseApi {
    runId: string
}

interface RunWithArtifacts {
    id: string
    artifacts?: readonly TaskRunArtifactResponseApi[] | null
}

/**
 * Agent files from every run of a task. A resumed task keeps writing new runs, so the files from earlier
 * runs in the chain are only on those runs. The first run that lists an id wins, so pass the live run first.
 */
export function collectRunArtifacts(runs: readonly (RunWithArtifacts | null | undefined)[]): RunArtifact[] {
    const byId = new Map<string, RunArtifact>()
    for (const run of runs) {
        if (!run) {
            continue
        }
        for (const artifact of visibleRunArtifacts(run.artifacts ?? [])) {
            if (artifact.id && !byId.has(artifact.id)) {
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
