export interface CodeownersEntry {
    pattern: string
    owners: string[]
}

export interface OwnerGroup {
    owner: string
    patterns: string[]
    index: number
}

export interface CodeownersError {
    /** 1-based line number. */
    line: number
    reason: string
}

const OWNER_RE = /^@[A-Za-z0-9/_.-]+$/
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/
const SECTION_HEADER_RE = /^\[[^\]]+\]$/

function isSkippableLine(line: string): boolean {
    return !line || line.startsWith('#') || SECTION_HEADER_RE.test(line)
}

/** Parse code owners-style text into (pattern, owners) entries. */
export function parseCodeowners(text: string): CodeownersEntry[] {
    const entries: CodeownersEntry[] = []
    for (const rawLine of text.split(/\r?\n/)) {
        const line = rawLine.trim()
        if (isSkippableLine(line)) {
            continue
        }

        const [pattern, ...owners] = line.split(/\s+/)
        if (pattern && owners.length > 0) {
            entries.push({ pattern, owners })
        }
    }
    return entries
}

/** Validate code owners-style text line by line. */
export function findCodeownersErrors(text: string): CodeownersError[] {
    const errors: CodeownersError[] = []
    text.split(/\r?\n/).forEach((rawLine, index) => {
        const line = rawLine.trim()
        if (isSkippableLine(line)) {
            return
        }

        const [, ...owners] = line.split(/\s+/)
        if (owners.length === 0) {
            errors.push({ line: index + 1, reason: 'Missing owner' })
            return
        }

        const invalid = owners.filter((owner) => !OWNER_RE.test(owner) && !EMAIL_RE.test(owner))
        if (invalid.length > 0) {
            errors.push({ line: index + 1, reason: 'Invalid owner' })
        }
    })
    return errors
}

/** Expand entries to one row per owner token, preserving source order. */
export function entriesByOwner(entries: CodeownersEntry[]): OwnerGroup[] {
    const groups: OwnerGroup[] = []
    for (const { pattern, owners } of entries) {
        for (const owner of owners) {
            groups.push({ owner, patterns: [pattern], index: groups.length })
        }
    }
    return groups
}
