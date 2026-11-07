import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { Button, Card, CardContent, Skeleton, Text } from '@posthog/quill'

import { CommitContent } from './artefactTypes'
import { QuillDiffBlock } from './QuillDiffBlock'
import { useArtefactCommitDiff } from './useArtefactCommitDiff'

/** The quill sibling of `ArtefactCommit`: the commit message, expanding to its diff on demand. */
export function QuillArtefactCommit({
    reportId,
    artefactId,
    content,
}: {
    reportId: string
    artefactId: string
    content: CommitContent
}): JSX.Element {
    const { expanded, setExpanded, diff, loading, error } = useArtefactCommitDiff(reportId, artefactId)
    const toggleLabel = expanded ? 'Hide commit diff' : 'Show commit diff'

    return (
        <Card size="sm" className="w-full">
            <CardContent className="flex min-w-0 flex-col gap-1">
                <div className="flex min-w-0 items-center gap-2">
                    <Text size="xs" render={<span />} className="min-w-0 flex-1 break-words">
                        {content.message}
                    </Text>
                    <Button
                        size="icon-sm"
                        aria-label={toggleLabel}
                        tooltip={toggleLabel}
                        aria-expanded={expanded}
                        onClick={() => setExpanded(!expanded)}
                        className="shrink-0"
                    >
                        {expanded ? <IconChevronDown /> : <IconChevronRight />}
                    </Button>
                </div>
                {content.note?.trim() ? (
                    <Text size="xs" variant="muted" render={<span />}>
                        {content.note}
                    </Text>
                ) : null}

                {expanded ? (
                    <div className="flex flex-col gap-1 border-t border-border pt-2">
                        {loading ? (
                            <div className="flex flex-col gap-1.5 py-1">
                                <Skeleton className="h-3 w-full" />
                                <Skeleton className="h-3 w-4/5" />
                            </div>
                        ) : error ? (
                            <Text size="xs" variant="destructive" render={<span />}>
                                {error}
                            </Text>
                        ) : diff && diff.diff.trim() ? (
                            <>
                                <QuillDiffBlock diff={diff.diff} />
                                {diff.truncated ? (
                                    <Text size="xs" render={<span />} className="text-subtle-foreground italic">
                                        The diff is truncated. Open the commit in GitHub to see the full change.
                                    </Text>
                                ) : null}
                            </>
                        ) : (
                            <Text size="xs" render={<span />} className="text-subtle-foreground">
                                No changes recorded for this commit.
                            </Text>
                        )}
                    </div>
                ) : null}
            </CardContent>
        </Card>
    )
}
