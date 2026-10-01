import type { TaskRunArtifactResponseApi } from 'products/tasks/frontend/generated/api.schemas'

export type TaskRunTab = 'conversation' | 'artifacts'

export type ArtifactPreviewKind = 'markdown' | 'html' | 'image' | 'csv' | 'text' | 'none'

export const ARTIFACT_KIND_LABEL: Record<ArtifactPreviewKind, string> = {
    markdown: 'Markdown',
    html: 'HTML',
    image: 'Image',
    csv: 'CSV',
    text: 'Text',
    none: 'File',
}

const TEXT_EXTENSIONS = ['txt', 'json', 'log', 'yaml', 'yml', 'xml', 'sql', 'py', 'ts', 'tsx', 'js', 'sh']

function extension(name: string): string {
    const dot = name.lastIndexOf('.')
    return dot === -1 ? '' : name.slice(dot + 1).toLowerCase()
}

export function artifactPreviewKind(artifact: TaskRunArtifactResponseApi): ArtifactPreviewKind {
    const contentType = (artifact.content_type ?? '').split(';')[0].trim().toLowerCase()
    const ext = extension(artifact.name)
    if (contentType === 'text/html' || ext === 'html' || ext === 'htm') {
        return 'html'
    }
    if (contentType.startsWith('image/') || ['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg'].includes(ext)) {
        return 'image'
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

/** Files the agent wrote for the user. Attachments, plans, skill bundles and dismissed files stay out. */
export function visibleRunArtifacts(artifacts: readonly TaskRunArtifactResponseApi[]): TaskRunArtifactResponseApi[] {
    return artifacts.filter(
        (artifact) =>
            !!artifact.id &&
            !!artifact.storage_path &&
            (artifact.type === 'output' || artifact.type === 'artifact') &&
            artifact.source === 'agent_output' &&
            !artifact.dismissed_at
    )
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
