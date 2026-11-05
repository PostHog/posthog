import type { MockPullRequest, MockReport } from './mockupData'

export function checksSummary(pullRequest: MockPullRequest): string {
    const { passed, failed, running } = pullRequest.checks
    return [`${passed} checks passed`, failed > 0 && `${failed} failed`, running > 0 && `${running} running`]
        .filter(Boolean)
        .join(', ')
}

export function rowFacts(report: MockReport): string[] {
    return [report.stateLabel, `Updated ${report.updated}`].filter((fact): fact is string => !!fact)
}

export function pullRequestLine(pullRequest: MockPullRequest): string {
    const changed = pullRequest.files.reduce(
        (total, file) => ({ additions: total.additions + file.additions, deletions: total.deletions + file.deletions }),
        { additions: 0, deletions: 0 }
    )
    const files = pullRequest.files.length === 1 ? '1 file' : `${pullRequest.files.length} files`
    return `#${pullRequest.number} · ${files}, +${changed.additions} −${changed.deletions}`
}
