import { parsePatchFiles } from '@pierre/diffs'
import type { FileDiffMetadata, FileDiffOptions } from '@pierre/diffs'
import { FileDiff } from '@pierre/diffs/react'
import { useValues } from 'kea'
import { useMemo } from 'react'

import { Button, Card, Item, ItemContent, ItemDescription } from '@posthog/quill-primitives'

import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { MAX_RENDERED_WIZARD_DIFF_LINES, wizardRunDiffCanRender } from '../wizardRunDisplay'
const DIFF_THEME = { light: 'github-light', dark: 'github-dark' } as const

function DiffNotice({
    children,
    pullRequestUrl,
    tone,
}: {
    children: string
    pullRequestUrl: string | null
    tone: 'warning' | 'destructive'
}): JSX.Element {
    return (
        <Item tone={tone} variant="outline">
            <ItemContent>
                <ItemDescription>{children}</ItemDescription>
                {pullRequestUrl && (
                    <Button variant="outline" size="sm" render={<LinkPrimitive to={pullRequestUrl} target="_blank" />}>
                        Open pull request
                    </Button>
                )}
            </ItemContent>
        </Item>
    )
}

function lineCounts(file: FileDiffMetadata): { additions: number; removals: number } {
    return file.hunks.reduce(
        (counts, hunk) => ({
            additions: counts.additions + hunk.additionLines,
            removals: counts.removals + hunk.deletionLines,
        }),
        { additions: 0, removals: 0 }
    )
}

function describeNonTextChange(file: FileDiffMetadata): string | null {
    if (file.hunks.length > 0) {
        return null
    }
    if (file.prevMode && file.mode && file.prevMode !== file.mode) {
        return `File mode changed from ${file.prevMode} to ${file.mode}.`
    }
    if (file.type === 'rename-pure') {
        return 'File renamed without content changes.'
    }
    // git diff --binary emits binary changes without text hunks.
    return 'Binary file changed. The content is not shown.'
}

export function WizardRunDiffViewer({
    diff,
    contentHash,
    sizeBytes,
    pullRequestUrl,
}: {
    diff: string
    contentHash: string
    sizeBytes: number
    pullRequestUrl: string | null
}): JSX.Element {
    const { isDarkModeOn } = useValues(themeLogic)
    const hasPullRequest = !!pullRequestUrl

    // Poll updates re-render the drawer with unchanged props, so parse only on real content changes.
    const parsed = useMemo<[boolean, FileDiffMetadata[]]>(() => {
        try {
            // throwOnError: the parser otherwise logs and returns an empty result, which reads
            // as "no changes" instead of a failure.
            return [false, parsePatchFiles(diff, contentHash, true).flatMap((patch) => patch.files)]
        } catch {
            return [true, []]
        }
    }, [diff, contentHash])
    const [parseFailed, files] = parsed

    if (!wizardRunDiffCanRender(sizeBytes)) {
        return (
            <DiffNotice tone="warning" pullRequestUrl={pullRequestUrl}>
                {hasPullRequest
                    ? 'This diff is too large to display here. Open the pull request to review the full change.'
                    : 'This diff is too large to display here.'}
            </DiffNotice>
        )
    }

    const renderedLines = files.reduce((total, file) => total + file.unifiedLineCount, 0)

    if (parseFailed) {
        return (
            <DiffNotice tone="destructive" pullRequestUrl={pullRequestUrl}>
                {hasPullRequest
                    ? "Couldn't display this diff. Open the pull request to review the changes."
                    : "Couldn't display this diff."}
            </DiffNotice>
        )
    }

    if (files.length === 0) {
        return <p className="m-0 text-sm text-muted">No file changes to display.</p>
    }

    if (renderedLines > MAX_RENDERED_WIZARD_DIFF_LINES) {
        return (
            <DiffNotice tone="warning" pullRequestUrl={pullRequestUrl}>
                {hasPullRequest
                    ? 'This diff has too many changes to display here. Open the pull request to review the full change.'
                    : 'This diff has too many changes to display here.'}
            </DiffNotice>
        )
    }

    const options: FileDiffOptions<never> = {
        theme: DIFF_THEME,
        themeType: isDarkModeOn ? 'dark' : 'light',
        diffStyle: 'unified',
        stickyHeader: true,
        overflow: 'scroll',
    }

    return (
        <div className="flex min-w-0 flex-col gap-3">
            {files.map((file) => {
                const counts = lineCounts(file)
                const path = file.prevName ? `${file.prevName} → ${file.name}` : file.name
                const nonTextChange = describeNonTextChange(file)
                const header = (
                    <div className="flex min-w-0 items-center gap-3 border-b border-primary bg-surface-secondary px-3 py-2">
                        <span className="truncate font-mono text-xs font-semibold" title={path}>
                            {path}
                        </span>
                        <span className="ml-auto flex shrink-0 gap-2 font-mono text-xs tabular-nums">
                            <span className="text-success">+{counts.additions.toLocaleString()}</span>
                            <span className="text-danger">-{counts.removals.toLocaleString()}</span>
                        </span>
                    </div>
                )

                return (
                    <Card key={`${file.name}-${file.cacheKey ?? ''}`} flush className="overflow-clip">
                        {nonTextChange ? (
                            <>
                                {header}
                                <p className="m-0 px-3 py-2 text-sm text-muted">{nonTextChange}</p>
                            </>
                        ) : (
                            <FileDiff<never>
                                fileDiff={file}
                                options={options}
                                renderCustomHeader={() => header}
                                disableWorkerPool
                            />
                        )}
                    </Card>
                )
            })}
        </div>
    )
}
