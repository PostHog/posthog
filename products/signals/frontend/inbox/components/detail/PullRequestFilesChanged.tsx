import { parsePatchFiles } from '@pierre/diffs'
import { useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { SignalReport } from '../../types'
import { CommitContent } from './artefactTypes'
import { DiffFileSummary, summarizeDiffFile } from './diffFileTree'
import { PullRequestDiffPanel } from './PullRequestDiffPanel'
import { DIFF_FILE_ATTR, diffFileElementId } from './PullRequestDiffView'
import { PullRequestFileTree } from './PullRequestFileTree'

function summarizeDiffFiles(diff: string, cacheKey: string): DiffFileSummary[] | null {
    if (!diff.trim()) {
        return []
    }
    try {
        return parsePatchFiles(diff, cacheKey)
            .flatMap((patch) => patch.files)
            .map(summarizeDiffFile)
    } catch {
        return null
    }
}

/**
 * "Files changed" tab body: a sticky file tree beside the stacked per-file diffs. The tree follows the
 * file at the top of the viewport as the page scrolls, and clicking a row scrolls its diff into view.
 * The diff itself is `PullRequestDiffPanel`, shared with the legacy tab, so nothing about loading,
 * inline comments, or the unified/split toggle lives here.
 */
export function PullRequestFilesChanged({
    report,
    commit,
}: {
    report: SignalReport
    commit: CommitContent
}): JSX.Element {
    const { reportDiff } = useValues(inboxReportDetailLogic({ reportId: report.id, report }))
    const files = useMemo(
        () => (reportDiff ? summarizeDiffFiles(reportDiff.diff, commit.commit_sha) : null),
        [reportDiff, commit.commit_sha]
    )
    const [activePath, setActivePath] = useState<string | null>(null)

    // Scroll-following is view state only: the row highlight tracks whichever file card crosses the
    // top third of the viewport. Cards mount asynchronously with the diff, so re-observe when `files` changes.
    useEffect(() => {
        if (!files?.length || typeof IntersectionObserver === 'undefined') {
            return
        }
        const cards = Array.from(document.querySelectorAll<HTMLElement>(`[${DIFF_FILE_ATTR}]`))
        if (cards.length === 0) {
            return
        }
        const visible = new Set<HTMLElement>()
        const observer = new IntersectionObserver(
            (entries) => {
                for (const entry of entries) {
                    if (entry.isIntersecting) {
                        visible.add(entry.target as HTMLElement)
                    } else {
                        visible.delete(entry.target as HTMLElement)
                    }
                }
                const first = cards.find((card) => visible.has(card))
                if (first) {
                    setActivePath(first.getAttribute(DIFF_FILE_ATTR))
                }
            },
            { rootMargin: '0px 0px -66% 0px' }
        )
        cards.forEach((card) => observer.observe(card))
        return () => observer.disconnect()
    }, [files])

    const selectFile = (path: string): void => {
        setActivePath(path)
        const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
        document
            .getElementById(diffFileElementId(path))
            ?.scrollIntoView({ block: 'start', behavior: reduceMotion ? 'auto' : 'smooth' })
    }

    return (
        <div className="flex items-start gap-6">
            {/* One file needs no tree. The tree also drops below @3xl, where the diff needs the full width. */}
            {files && files.length > 1 && (
                <div
                    className="hidden @3xl:block w-72 shrink-0 sticky top-0 max-h-screen overflow-y-auto py-1 pr-2"
                    data-attr="inbox-pr-file-tree"
                >
                    <PullRequestFileTree files={files} activePath={activePath} onSelectFile={selectFile} />
                </div>
            )}
            <div className="min-w-0 flex-1">
                <PullRequestDiffPanel report={report} commit={commit} />
            </div>
        </div>
    )
}
