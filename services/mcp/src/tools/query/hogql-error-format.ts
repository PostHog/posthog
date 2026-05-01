import { PostHogValidationError } from '@/lib/errors'

interface HogQLNotice {
    message: string
    start?: number | null
    end?: number | null
    fix?: string | null
}

interface HogQLMetadataPayload {
    isValid?: boolean
    query?: string
    errors?: HogQLNotice[]
    warnings?: HogQLNotice[]
    notices?: HogQLNotice[]
    table_names?: string[]
    ch_table_names?: string[]
}

/**
 * Pulls the structured `hogql_metadata` blob off a PostHog validation error's
 * `extra` bag, if present. The backend attaches it on any failed HogQL query
 * so callers can surface positions, table refs, and fix hints to agents
 * instead of a bare detail string.
 */
export function extractHogQLMetadata(error: unknown): HogQLMetadataPayload | undefined {
    if (!(error instanceof PostHogValidationError) || !error.extra) {
        return undefined
    }
    const payload = error.extra['hogql_metadata']
    if (!payload || typeof payload !== 'object') {
        return undefined
    }
    return payload as HogQLMetadataPayload
}

function formatNotice(notice: HogQLNotice): string {
    const parts: string[] = [notice.message]
    if (typeof notice.start === 'number' && typeof notice.end === 'number') {
        parts.push(`(chars ${notice.start}-${notice.end})`)
    }
    if (notice.fix) {
        parts.push(`— fix: ${notice.fix}`)
    }
    return parts.join(' ')
}

/**
 * Renders a multi-line string for a HogQL failure that an agent can read
 * directly. Safe to call with `undefined`: returns an empty string in that
 * case so callers can append unconditionally.
 */
export function formatHogQLMetadataForAgent(metadata: HogQLMetadataPayload | undefined): string {
    if (!metadata) {
        return ''
    }

    const sections: string[] = []

    if (metadata.errors && metadata.errors.length > 0) {
        sections.push('HogQL errors:\n' + metadata.errors.map((e) => `  - ${formatNotice(e)}`).join('\n'))
    }

    if (metadata.warnings && metadata.warnings.length > 0) {
        sections.push('Warnings:\n' + metadata.warnings.map((w) => `  - ${formatNotice(w)}`).join('\n'))
    }

    if (metadata.notices && metadata.notices.length > 0) {
        sections.push('Notices:\n' + metadata.notices.map((n) => `  - ${formatNotice(n)}`).join('\n'))
    }

    if (metadata.table_names && metadata.table_names.length > 0) {
        sections.push(`Tables referenced: ${metadata.table_names.join(', ')}`)
    }

    return sections.join('\n\n')
}
