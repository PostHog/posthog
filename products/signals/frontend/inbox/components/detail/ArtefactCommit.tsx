import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { CommitContent } from './artefactTypes'
import { DiffBlock } from './DiffBlock'
import { useArtefactCommitDiff } from './useArtefactCommitDiff'

export function ArtefactCommit({
    reportId,
    artefactId,
    content,
}: {
    reportId: string
    artefactId: string
    content: CommitContent
}): JSX.Element {
    const { expanded, setExpanded, diff, loading, error } = useArtefactCommitDiff(reportId, artefactId)

    return (
        <LemonCard hoverEffect={false} className="w-full p-2 shadow-none">
            <div className="flex min-w-0 items-center gap-2">
                <span className="min-w-0 flex-1 text-xs text-default">{content.message}</span>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={expanded ? <IconChevronDown /> : <IconChevronRight />}
                    aria-label={expanded ? 'Hide commit diff' : 'Show commit diff'}
                    onClick={() => setExpanded(!expanded)}
                    className="shrink-0"
                />
            </div>
            {content.note?.trim() ? <span className="block text-secondary text-xs mt-1">{content.note}</span> : null}

            {expanded ? (
                <div className="mt-2 border-t pt-2">
                    {loading ? (
                        <div className="flex flex-col gap-1.5 py-1">
                            <LemonSkeleton className="h-3 w-full" />
                            <LemonSkeleton className="h-3 w-4/5" />
                        </div>
                    ) : error ? (
                        <span className="text-xs text-danger">{error}</span>
                    ) : diff && diff.diff.trim() ? (
                        <>
                            <DiffBlock diff={diff.diff} />
                            {diff.truncated ? (
                                <span className="mt-1 block text-xs text-tertiary italic">
                                    The diff is truncated. Open the commit in GitHub to see the full change.
                                </span>
                            ) : null}
                        </>
                    ) : (
                        <span className="text-xs text-tertiary">No changes recorded for this commit.</span>
                    )}
                </div>
            ) : null}
        </LemonCard>
    )
}
