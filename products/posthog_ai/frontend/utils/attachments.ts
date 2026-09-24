/** A file staged in the composer, not yet uploaded. */
export interface PendingAttachment {
    id: string
    file: File
}

/** The artifact API's ceiling: `size` on a prepare request is capped at 31457280. */
export const ATTACHMENT_MAX_SIZE_BYTES = 30 * 1024 * 1024
/** A larger PDF is rejected by the model, so it would fail the run after a successful upload. */
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

export function getFileExtension(fileName: string): string {
    const parts = fileName.split('.')
    return parts.length > 1 ? (parts.at(-1)?.toLowerCase() ?? '') : ''
}

/**
 * Derived from the extension rather than read off `File.type`: browsers report some text files as
 * `application/octet-stream`, and the sandbox derives the agent's view of the file from what is recorded
 * here.
 */
export function inferContentType(fileName: string): string {
    return CONTENT_TYPE_BY_EXTENSION[getFileExtension(fileName)] ?? DEFAULT_CONTENT_TYPE
}

export function maxSizeBytesFor(fileName: string): number {
    return getFileExtension(fileName) === 'pdf' ? PDF_ATTACHMENT_MAX_SIZE_BYTES : ATTACHMENT_MAX_SIZE_BYTES
}

export function isImageAttachment(fileName: string): boolean {
    return inferContentType(fileName).startsWith('image/')
}

export function attachmentRejectionReason(file: File): string | null {
    if (file.size === 0) {
        return `${file.name} is empty`
    }
    const maxSizeBytes = maxSizeBytesFor(file.name)
    if (file.size > maxSizeBytes) {
        const maxMb = Math.floor(maxSizeBytes / (1024 * 1024))
        return getFileExtension(file.name) === 'pdf'
            ? `${file.name} is over the ${maxMb}MB limit for PDFs`
            : `${file.name} is over the ${maxMb}MB limit`
    }
    return null
}

export function formatFileSize(bytes: number): string {
    if (bytes < 1024) {
        return `${bytes} B`
    }
    if (bytes < 1024 * 1024) {
        return `${Math.round(bytes / 1024)} KB`
    }
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
