import { percentage } from 'lib/utils/numbers'

import type { AudienceSlice, KnownPattern, RelatedIssuesIssue } from '../recommendations/types'

// Flow and page paths arrive as host plus normalized path. The host is the same on every row, so drop it.
export function shortPath(path: string): string {
    const slash = path.indexOf('/')
    return slash === -1 ? '/' : path.slice(slash)
}

export function share(value: number): string {
    return percentage(value, value > 0 && value < 0.01 ? 1 : 0)
}

// How many times the usual rate. Large multipliers lose their decimals, small ones keep one.
export function multiplier(value: number, usual: number): string {
    if (usual <= 0) {
        return 'new'
    }
    const times = value / usual
    return times >= 10 ? `${Math.round(times)}×` : `${times.toFixed(1)}×`
}

export const AUDIENCE_DIMENSION_LABELS: Record<AudienceSlice['dimension'], string> = {
    browser: 'browser',
    browser_version: 'browser version',
    os: 'operating system',
    device_type: 'device type',
    user_agent: 'kind of visitor',
}

const USER_AGENT_LABELS: Record<string, string> = {
    bot: 'Bots',
    in_app_browser: 'In-app browsers',
    webview: 'Webviews',
}

export function sliceLabel(slice: AudienceSlice): string {
    return slice.dimension === 'user_agent' ? (USER_AGENT_LABELS[slice.value] ?? slice.value) : slice.value
}

export const KNOWN_PATTERN_LABELS: Record<KnownPattern, string> = {
    extension: 'Browser extension',
    resize_observer: 'ResizeObserver loop',
    script_error: 'Cross-origin script error',
    chunk_load: 'Chunk failed to load',
    hydration: 'Hydration mismatch',
    abort: 'Aborted request',
    network: 'Network failure',
    non_error_rejection: 'Non-error rejection',
    environment: 'Webview or link scanner',
    http_status: 'HTTP error',
    code_bug: 'Code bug',
    other: 'Other',
}

const issueLabel = (issue: { name: string; description: string | null }): string => issue.description || issue.name

export function relatedPairTitle(pair: RelatedIssuesIssue): string {
    if (pair.relation === 'same') {
        return `${issueLabel(pair)} is filed twice`
    }
    const connector = pair.relation === 'causes' ? 'leads to' : 'fires with'
    return `${issueLabel(pair)} ${connector} ${issueLabel(pair.related)}`
}
