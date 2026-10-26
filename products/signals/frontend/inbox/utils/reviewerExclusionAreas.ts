import type { RepoSelectionContent, SignalFindingContent } from '../components/detail/artefactTypes'
import type { SignalReportArtefact } from '../types'

/** An area a person can stay off. An empty `pathPrefix` covers the whole repository. */
export interface ReviewerExclusionArea {
    repository: string
    pathPrefix: string
}

const MAX_PATH_AREAS = 3

function normalizedPath(path: string): string {
    return path
        .trim()
        .replace(/^\.\//, '')
        .replace(/^\/+|\/+$/g, '')
}

function latest(artefacts: SignalReportArtefact[], type: string): SignalReportArtefact[] {
    return artefacts.filter((artefact) => artefact.type === type).sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
}

/**
 * The areas a person can stay off, from a report's selected repository and the paths of its current findings.
 * A path exclusion matches a report by whole path segments of its finding paths, the way the backend's
 * `StandingExclusions` reads them, so only directories that hold a finding path are offered. Any other
 * prefix would not even cover the report the person is leaving. The most specific areas come first, and
 * the whole repository comes last because it is the broadest rule.
 */
export function reviewerExclusionAreas(artefacts: SignalReportArtefact[]): ReviewerExclusionArea[] {
    const selection = latest(artefacts, 'repo_selection')[0]?.content as RepoSelectionContent | undefined
    const repository = selection?.repository?.trim().toLowerCase()
    if (!repository) {
        return []
    }

    // Re-research supersedes a signal's older findings, so read only each signal's newest one.
    const currentPaths = new Map<string, string[]>()
    for (const artefact of latest(artefacts, 'signal_finding')) {
        const content = artefact.content as SignalFindingContent
        if (!currentPaths.has(content.signal_id)) {
            currentPaths.set(content.signal_id, content.relevant_code_paths ?? [])
        }
    }
    const paths = [...new Set([...currentPaths.values()].flat().map(normalizedPath).filter(Boolean))]

    const coverage = new Map<string, number>()
    for (const path of paths) {
        const segments = path.split('/')
        for (let depth = 1; depth < segments.length; depth++) {
            const directory = segments.slice(0, depth).join('/')
            coverage.set(directory, (coverage.get(directory) ?? 0) + 1)
        }
    }
    const directories = [...coverage.entries()]
        .sort(([a, aCount], [b, bCount]) => bCount - aCount || b.split('/').length - a.split('/').length)
        .slice(0, MAX_PATH_AREAS)
        .map(([pathPrefix]) => ({ repository, pathPrefix }))

    return [...directories, { repository, pathPrefix: '' }]
}

export function reviewerExclusionAreaLabel(area: { repository: string; pathPrefix: string }): string {
    return area.pathPrefix ? `${area.repository}/${area.pathPrefix}` : `All of ${area.repository}`
}
