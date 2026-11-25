import type { ErrorTrackingIssueReadApi } from '../../generated/api.schemas'

export function IssueResolvedRule({
    resolvedUntil,
    latestRelease,
}: {
    resolvedUntil: ErrorTrackingIssueReadApi['resolved_until'] | undefined
    latestRelease: ErrorTrackingIssueReadApi['latest_release'] | undefined
}): JSX.Element {
    if (resolvedUntil !== 'new_release') {
        return (
            <span>
                Resolved until the next occurrence. It reopens the next time it happens, even in an existing release.
            </span>
        )
    }
    if (!latestRelease) {
        return <span>No release has been seen for this issue yet, so it reopens the next time it happens.</span>
    }
    return (
        <span>
            Stays resolved for exceptions from release{' '}
            <span className="font-semibold break-words">{latestRelease.version}</span> or older releases. It reopens if
            it happens again in a newer release, or without a release.
        </span>
    )
}
