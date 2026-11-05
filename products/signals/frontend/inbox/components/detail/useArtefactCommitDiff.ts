import { useValues } from 'kea'
import { useEffect, useState } from 'react'

import { teamLogic } from 'scenes/teamLogic'

import { signalsReportArtefactsDiff } from 'products/signals/frontend/generated/api'
import type { CommitDiffResponseApi } from 'products/signals/frontend/generated/api.schemas'

export interface ArtefactCommitDiffState {
    expanded: boolean
    setExpanded: (expanded: boolean) => void
    diff: CommitDiffResponseApi | null
    loading: boolean
    error: string | null
}

/** A commit entry's expanded state and its lazily fetched diff, shared by `ArtefactCommit` and its quill sibling. */
export function useArtefactCommitDiff(reportId: string, artefactId: string): ArtefactCommitDiffState {
    const { currentTeamId } = useValues(teamLogic)
    const [expanded, setExpanded] = useState(false)
    const [diff, setDiff] = useState<CommitDiffResponseApi | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    // Fetch the diff only once, on first expand — commit diffs are immutable, so there's no reason
    // to refetch. Keyed on artefactId so a recycled component instance refetches for a new commit;
    // `currentTeamId` is a dep so a late-arriving team still triggers the fetch once available.
    useEffect(() => {
        if (!expanded || diff || loading || error || !currentTeamId) {
            return
        }
        setLoading(true)
        let cancelled = false
        signalsReportArtefactsDiff(String(currentTeamId), reportId, artefactId)
            .then((response) => {
                if (!cancelled) {
                    setDiff(response)
                }
            })
            .catch(() => {
                if (!cancelled) {
                    setError(
                        "Couldn't load this commit's diff. Open the commit in GitHub to check whether it was rewritten or removed."
                    )
                }
            })
            .finally(() => {
                if (!cancelled) {
                    setLoading(false)
                }
            })
        return () => {
            cancelled = true
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [expanded, artefactId, currentTeamId])

    return { expanded, setExpanded, diff, loading, error }
}
