import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { IconCollapse, IconExpand } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import type { AcpMessage } from '../conversation/acp-types'
import { DiffStatsChip } from '../conversation/DiffStatsChip'
import type { TaskRun } from '../types'
import {
    type ChangedFile,
    type FileDiffText,
    buildToolCallSummary,
    extractChangedFilesFromToolCalls,
    extractFileDiff,
    parseRunOutputFiles,
} from './deriveChangedFiles'
import { FileDiff } from './FileDiff'

export interface ReviewPanelProps {
    run: TaskRun | null
    events: AcpMessage[]
    /** When set (e.g. from a conversation file mention), the panel expands and scrolls to that file. */
    requestedFilePath?: string | null
}

/**
 * Read-only "Changes" review panel for a cloud task run: lists the files the
 * agent changed with per-file diff stats, each expandable into a diff view.
 * Diffs are derived from run.output file metadata when present, otherwise
 * reconstructed from write/edit tool-call DiffContent in the event stream.
 */
export function ReviewPanel({ run, events, requestedFilePath }: ReviewPanelProps): JSX.Element {
    const toolCalls = useMemo(() => buildToolCallSummary(events), [events])
    const files = useMemo<ChangedFile[]>(
        () => parseRunOutputFiles(run) ?? extractChangedFilesFromToolCalls(toolCalls),
        [run, toolCalls]
    )

    const diffs = useMemo<Map<string, FileDiffText>>(() => {
        const map = new Map<string, FileDiffText>()
        for (const file of files) {
            const diff = extractFileDiff(toolCalls, file.path)
            if (diff) {
                map.set(file.path, diff)
            }
        }
        return map
    }, [files, toolCalls])

    const totals = useMemo(
        () =>
            files.reduce(
                (acc, file) => ({
                    added: acc.added + (file.linesAdded ?? 0),
                    removed: acc.removed + (file.linesRemoved ?? 0),
                }),
                { added: 0, removed: 0 }
            ),
        [files]
    )

    // Expanded-set model: files start collapsed so heavy diff bodies mount lazily
    const [expandedFiles, setExpandedFiles] = useState<Set<string>>(new Set())
    const allExpanded = files.length > 0 && files.every((file) => expandedFiles.has(file.path))

    const toggleFile = useCallback((path: string): void => {
        setExpandedFiles((previous) => {
            const next = new Set(previous)
            if (next.has(path)) {
                next.delete(path)
            } else {
                next.add(path)
            }
            return next
        })
    }, [])

    const expandAll = useCallback((): void => setExpandedFiles(new Set(files.map((file) => file.path))), [files])
    const collapseAll = useCallback((): void => setExpandedFiles(new Set()), [])

    // Scroll + uncollapse on external navigation requests (presentational concern, so a hook is fine)
    const fileRefs = useRef<Map<string, HTMLDivElement>>(new Map())
    useEffect(() => {
        if (!requestedFilePath) {
            return
        }
        const match = files.find(
            (file) => file.path === requestedFilePath || file.path.endsWith(`/${requestedFilePath}`)
        )
        if (!match) {
            return
        }
        setExpandedFiles((previous) => new Set([...previous, match.path]))
        requestAnimationFrame(() => {
            fileRefs.current.get(match.path)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
        })
    }, [requestedFilePath, files])

    if (files.length === 0) {
        return (
            <div className="flex h-full flex-col items-center justify-center gap-1 p-8 text-center">
                <div className="font-semibold">No changes yet</div>
                <div className="text-muted text-sm">File changes made by the agent will show up here</div>
            </div>
        )
    }

    return (
        <div className="flex h-full min-h-0 flex-col">
            <div className="flex shrink-0 items-center gap-2 border-b px-3 py-2">
                <span className="font-semibold">Changes</span>
                <span className="text-muted text-xs">
                    {files.length} {files.length === 1 ? 'file' : 'files'}
                </span>
                <DiffStatsChip additions={totals.added} deletions={totals.removed} />
                <div className="ml-auto flex items-center gap-1">
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconExpand />}
                        onClick={expandAll}
                        disabledReason={allExpanded ? 'All files are already expanded' : undefined}
                        tooltip="Expand all files"
                    >
                        Expand all
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        icon={<IconCollapse />}
                        onClick={collapseAll}
                        disabledReason={expandedFiles.size === 0 ? 'All files are already collapsed' : undefined}
                        tooltip="Collapse all files"
                    >
                        Collapse all
                    </LemonButton>
                </div>
            </div>
            <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto p-3">
                {files.map((file) => (
                    <div
                        key={file.path}
                        ref={(element) => {
                            if (element) {
                                fileRefs.current.set(file.path, element)
                            } else {
                                fileRefs.current.delete(file.path)
                            }
                        }}
                    >
                        <FileDiff
                            file={file}
                            collapsed={!expandedFiles.has(file.path)}
                            onToggle={() => toggleFile(file.path)}
                            diff={diffs.get(file.path) ?? null}
                        />
                    </div>
                ))}
            </div>
        </div>
    )
}
