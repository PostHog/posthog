import { useState } from 'react'

import { IconExpand45 } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'

function DiffPanes({
    original,
    modified,
    onChange,
    editable,
    isDarkModeOn,
    editorHeight,
    onExpand,
    originalTitle,
    modifiedTitle,
}: {
    original: string | null
    modified: string | null
    onChange?: (value: string) => void
    editable?: boolean
    isDarkModeOn: boolean
    editorHeight?: string
    onExpand?: () => void
    originalTitle: string
    modifiedTitle: string
}): JSX.Element {
    return (
        <div className="@container border rounded overflow-hidden">
            <div className="flex items-center border-b bg-surface-secondary text-xs font-medium">
                {/* Shown exactly when Monaco renders side by side: its inline flip is on editor width (renderSideBySideInlineBreakpoint), not the viewport. */}
                <div className="hidden @[480px]:block flex-1 px-3 py-1.5 border-r">{originalTitle}</div>
                <div className="flex-1 px-3 py-1.5 flex items-center justify-between">
                    <span>{modifiedTitle}</span>
                    {onExpand && (
                        <LemonButton
                            size="xsmall"
                            icon={<IconExpand45 />}
                            tooltip="Expand diff to full screen"
                            onClick={onExpand}
                            data-attr="vision-calibration-expand-diff"
                        />
                    )}
                </div>
            </div>
            <MonacoDiffEditor
                original={original}
                modified={modified}
                onChange={onChange ? (value) => onChange(value) : undefined}
                modifiedEditable={editable}
                language="markdown"
                theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
                height={editorHeight}
                options={{
                    renderSideBySide: true,
                    useInlineViewWhenSpaceIsLimited: true,
                    renderSideBySideInlineBreakpoint: 480,
                    // Keep both panes at exactly half width on resize, in lockstep with the header row.
                    enableSplitViewResizing: false,
                    splitViewDefaultRatio: 0.5,
                    automaticLayout: true,
                    wordWrap: 'on',
                    lineNumbers: 'off',
                    folding: false,
                    renderOverviewRuler: false,
                    scrollBeyondLastLine: false,
                    diffAlgorithm: 'advanced',
                }}
            />
        </div>
    )
}

/** The prompt diff, expandable to full screen. Both instances share one onChange. */
export function PromptDiff({
    original,
    modified,
    onChange,
    editable,
    isDarkModeOn,
}: {
    original: string | null
    modified: string | null
    onChange?: (value: string) => void
    editable?: boolean
    isDarkModeOn: boolean
}): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    const titles = {
        originalTitle: 'Current prompt',
        modifiedTitle: editable ? 'New prompt (edit directly)' : 'New prompt',
    }
    return (
        <>
            <DiffPanes
                original={original}
                modified={modified}
                onChange={onChange}
                editable={editable}
                isDarkModeOn={isDarkModeOn}
                onExpand={() => setIsExpanded(true)}
                {...titles}
            />
            <LemonModal isOpen={isExpanded} onClose={() => setIsExpanded(false)} title="Recommendation" fullScreen>
                <DiffPanes
                    original={original}
                    modified={modified}
                    onChange={onChange}
                    editable={editable}
                    isDarkModeOn={isDarkModeOn}
                    editorHeight="calc(100vh - 16rem)"
                    {...titles}
                />
            </LemonModal>
        </>
    )
}

/** Opens a read-only prompt diff in a modal, for surfaces too dense to embed an editor per row. */
export function PromptDiffButton({
    original,
    modified,
    originalTitle,
    modifiedTitle,
    isDarkModeOn,
}: {
    original: string | null
    modified: string | null
    originalTitle: string
    modifiedTitle: string
    isDarkModeOn: boolean
}): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    return (
        <>
            <LemonButton size="xsmall" type="secondary" onClick={() => setIsOpen(true)} data-attr="vision-version-diff">
                See what changed
            </LemonButton>
            <LemonModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                title={`Prompt: ${originalTitle} to ${modifiedTitle}`}
                fullScreen
            >
                <DiffPanes
                    original={original}
                    modified={modified}
                    isDarkModeOn={isDarkModeOn}
                    editorHeight="calc(100vh - 16rem)"
                    originalTitle={originalTitle}
                    modifiedTitle={modifiedTitle}
                />
            </LemonModal>
        </>
    )
}
