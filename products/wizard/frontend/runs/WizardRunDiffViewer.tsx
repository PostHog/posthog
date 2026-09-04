import { parsePatchFiles } from '@pierre/diffs'
import type { FileDiffMetadata, FileDiffOptions } from '@pierre/diffs'
import { FileDiff } from '@pierre/diffs/react'
import { useValues } from 'kea'

import { LemonBanner, LemonCard } from '@posthog/lemon-ui'

import { themeLogic } from '~/layout/navigation-3000/themeLogic'

import { wizardRunDiffCanRender } from '../wizardRunDisplay'
const DIFF_THEME = { light: 'github-light', dark: 'github-dark' } as const

function lineCounts(file: FileDiffMetadata): { additions: number; removals: number } {
    return file.hunks.reduce(
        (counts, hunk) => ({
            additions: counts.additions + hunk.additionLines,
            removals: counts.removals + hunk.deletionLines,
        }),
        { additions: 0, removals: 0 }
    )
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
    const pullRequestAction = pullRequestUrl
        ? { children: 'Open pull request', to: pullRequestUrl, targetBlank: true }
        : undefined

    if (!wizardRunDiffCanRender(sizeBytes)) {
        return (
            <LemonBanner type="warning" action={pullRequestAction}>
                This diff is too large to display here. Open the pull request to review the full change.
            </LemonBanner>
        )
    }

    let files: FileDiffMetadata[]
    try {
        files = parsePatchFiles(diff, contentHash).flatMap((patch) => patch.files)
    } catch {
        return (
            <LemonBanner type="error" action={pullRequestAction}>
                Couldn't display this diff. Open the pull request to review the changes.
            </LemonBanner>
        )
    }

    if (files.length === 0) {
        return <p className="m-0 text-sm text-muted">No file changes to display.</p>
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

                return (
                    <LemonCard
                        key={`${file.name}-${file.cacheKey ?? ''}`}
                        hoverEffect={false}
                        className="p-0 overflow-hidden"
                    >
                        <FileDiff<never>
                            fileDiff={file}
                            options={options}
                            renderCustomHeader={() => (
                                <div className="flex min-w-0 items-center gap-3 border-b border-primary bg-surface-secondary px-3 py-2">
                                    <span className="truncate font-mono text-xs font-semibold" title={path}>
                                        {path}
                                    </span>
                                    <span className="ml-auto flex shrink-0 gap-2 font-mono text-xs tabular-nums">
                                        <span className="text-success">+{counts.additions.toLocaleString()}</span>
                                        <span className="text-danger">-{counts.removals.toLocaleString()}</span>
                                    </span>
                                </div>
                            )}
                            disableWorkerPool
                        />
                    </LemonCard>
                )
            })}
        </div>
    )
}
