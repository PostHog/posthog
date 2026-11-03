import clsx from 'clsx'
import { useMemo } from 'react'

import { pluralize } from 'lib/utils/strings'

import { ContentAutopilotDiffLine, collapseUnchangedLines, diffLines } from './diffLines'

export interface ContentAutopilotLineDiffProps {
    before: string
    after: string
}

const LINE_STYLES: Record<ContentAutopilotDiffLine['kind'], { sign: string; className: string }> = {
    same: { sign: ' ', className: '' },
    added: { sign: '+', className: 'bg-success-highlight text-success' },
    removed: { sign: '-', className: 'bg-danger-highlight text-danger' },
}

export const ContentAutopilotLineDiff = ({ before, after }: ContentAutopilotLineDiffProps): JSX.Element => {
    const lines = useMemo(() => diffLines(before, after), [before, after])
    const added = lines.filter(({ kind }) => kind === 'added').length
    const removed = lines.filter(({ kind }) => kind === 'removed').length

    if (added === 0 && removed === 0) {
        return <p className="m-0 text-muted">This draft doesn't change the page.</p>
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="text-sm text-muted">
                {pluralize(added, 'line')} added, {pluralize(removed, 'line')} removed
            </div>
            <div className="max-h-160 overflow-auto rounded border font-mono text-xs">
                {collapseUnchangedLines(lines).map((segment, index) =>
                    segment.kind === 'collapsed' ? (
                        <div key={index} className="px-3 py-1 text-muted bg-surface-secondary border-y">
                            {pluralize(segment.count, 'unchanged line')}
                        </div>
                    ) : (
                        <div
                            key={index}
                            className={clsx(
                                'flex gap-3 px-3 whitespace-pre-wrap',
                                LINE_STYLES[segment.line.kind].className
                            )}
                        >
                            <span className="select-none w-2 shrink-0">{LINE_STYLES[segment.line.kind].sign}</span>
                            <span className="min-w-0 break-words">{segment.line.text || ' '}</span>
                        </div>
                    )
                )}
            </div>
        </div>
    )
}
