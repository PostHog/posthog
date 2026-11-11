import type { AttachmentRejectionReason, PendingAttachment, PickedFile } from './types'

// The same limits and content types as `products/posthog_ai/frontend/utils/attachments.ts`.

/** The artifact API's ceiling: `size` on a prepare request is capped at 31457280. */
export const ATTACHMENT_MAX_SIZE_BYTES = 30 * 1024 * 1024
/** The model rejects a larger PDF, which would fail the run after a successful upload. */
export const PDF_ATTACHMENT_MAX_SIZE_BYTES = 10 * 1024 * 1024
export const MAX_ATTACHMENTS_PER_MESSAGE = 10

const CONTENT_TYPE_BY_EXTENSION: Record<string, string> = {
    bmp: 'image/bmp',
    c: 'text/plain',
    cc: 'text/plain',
    conf: 'text/plain',
    cpp: 'text/plain',
    css: 'text/css',
    csv: 'text/csv',
    gif: 'image/gif',
    go: 'text/plain',
    h: 'text/plain',
    html: 'text/html',
    ini: 'text/plain',
    java: 'text/plain',
    jpeg: 'image/jpeg',
    jpg: 'image/jpeg',
    js: 'text/javascript',
    json: 'application/json',
    jsx: 'text/javascript',
    log: 'text/plain',
    md: 'text/markdown',
    pdf: 'application/pdf',
    png: 'image/png',
    py: 'text/x-python',
    rb: 'text/plain',
    rs: 'text/plain',
    sh: 'text/x-shellscript',
    sql: 'application/sql',
    svg: 'image/svg+xml',
    toml: 'application/toml',
    ts: 'text/typescript',
    tsx: 'text/typescript',
    txt: 'text/plain',
    webp: 'image/webp',
    xml: 'application/xml',
    yaml: 'application/yaml',
    yml: 'application/yaml',
    zip: 'application/zip',
}

const DEFAULT_CONTENT_TYPE = 'application/octet-stream'

export function fileExtension(name: string): string {
    const parts = name.split('.')
    return parts.length > 1 ? (parts.at(-1)?.toLowerCase() ?? '') : ''
}

export function contentTypeFor(name: string): string {
    return CONTENT_TYPE_BY_EXTENSION[fileExtension(name)] ?? DEFAULT_CONTENT_TYPE
}

export function isImageName(name: string): boolean {
    return contentTypeFor(name).startsWith('image/')
}

function maxSizeFor(name: string): number {
    return fileExtension(name) === 'pdf' ? PDF_ATTACHMENT_MAX_SIZE_BYTES : ATTACHMENT_MAX_SIZE_BYTES
}

export function rejectionReason(file: PickedFile): AttachmentRejectionReason | null {
    if (file.size === null) {
        return 'unreadable'
    }
    if (file.size === 0) {
        return 'empty'
    }
    return file.size > maxSizeFor(file.name) ? 'too_large' : null
}

export interface AttachmentRejection {
    name: string
    reason: AttachmentRejectionReason
}

export interface AttachmentPick {
    added: PendingAttachment[]
    rejected: AttachmentRejection[]
    /** Files that passed the limits but did not fit under the per-message cap. */
    leftOff: number
}

/** Applies the limits to a pick, then fills the free slots in pick order, as the web composer does. */
export function addPickedFiles(
    current: readonly PendingAttachment[],
    picked: readonly PickedFile[],
    makeId: () => string
): AttachmentPick {
    const rejected: AttachmentRejection[] = []
    const acceptable: PendingAttachment[] = []
    for (const file of picked) {
        const reason = rejectionReason(file)
        if (reason) {
            rejected.push({ name: file.name, reason })
            continue
        }
        const contentType = contentTypeFor(file.name)
        acceptable.push({
            id: makeId(),
            uri: file.uri,
            name: file.name,
            size: file.size ?? 0,
            contentType,
            isImage: contentType.startsWith('image/'),
            ...(file.webFile ? { webFile: file.webFile } : {}),
        })
    }
    const slots = Math.max(0, MAX_ATTACHMENTS_PER_MESSAGE - current.length)
    return { added: acceptable.slice(0, slots), rejected, leftOff: Math.max(0, acceptable.length - slots) }
}

function rejectionText({ name, reason }: AttachmentRejection): string {
    switch (reason) {
        case 'empty':
            return `${name} is empty.`
        case 'unreadable':
            return `Couldn't read ${name}. Try another file.`
        case 'too_large':
            return fileExtension(name) === 'pdf'
                ? `${name} is over the 10 MB limit for PDFs.`
                : `${name} is over the 30 MB limit.`
    }
}

export function pickNotice(pick: AttachmentPick): string | undefined {
    const lines = pick.rejected.map(rejectionText)
    if (pick.leftOff > 0) {
        const verb = pick.leftOff === 1 ? 'was' : 'were'
        lines.push(`Only ${MAX_ATTACHMENTS_PER_MESSAGE} files fit in one message, so ${pick.leftOff} ${verb} left off.`)
    }
    return lines.length > 0 ? lines.join(' ') : undefined
}
