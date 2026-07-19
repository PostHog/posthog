import { useState } from 'react'

import { IconExpand45 } from '@posthog/icons'
import { LemonButton, LemonModal, LemonTag, LemonTagType } from '@posthog/lemon-ui'

import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'
import { identifierToHuman } from 'lib/utils/strings'

import type { ReplayScannerPromptSuggestionApi } from '../../generated/api.schemas'
import { describeTagOp, formatChangeValue, parseConfigChanges, ScannerConfigChange } from './configChanges'

/** The bordered side-by-side diff with labeled panes, rendered inline and inside the fullscreen modal. */
function SuggestionDiffPanes({
    suggestion,
    beforeLabel,
    isDarkModeOn,
    editorHeight,
    onExpand,
}: {
    suggestion: ReplayScannerPromptSuggestionApi
    beforeLabel: string
    isDarkModeOn: boolean
    editorHeight?: string
    onExpand?: () => void
}): JSX.Element {
    return (
        <div className="border rounded overflow-hidden">
            <div className="flex items-center border-b bg-surface-secondary text-xs font-medium">
                <div className="flex-1 px-3 py-1.5 border-r">{beforeLabel}</div>
                <div className="flex-1 px-3 py-1.5 flex items-center justify-between">
                    <span>Suggested prompt</span>
                    {onExpand && (
                        <LemonButton
                            size="xsmall"
                            icon={<IconExpand45 />}
                            tooltip="Expand diff to full screen"
                            onClick={onExpand}
                            data-attr="vision-quality-expand-diff"
                        />
                    )}
                </div>
            </div>
            <MonacoDiffEditor
                original={suggestion.base_prompt}
                modified={suggestion.suggested_prompt}
                language="markdown"
                theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
                height={editorHeight}
                options={{
                    readOnly: true,
                    renderSideBySide: true,
                    useInlineViewWhenSpaceIsLimited: false,
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

/** The prompt card: a diff when there's a prior prompt to compare against, plain text otherwise (first-ever suggestion). */
function PromptChangeCard({
    suggestion,
    isDarkModeOn,
}: {
    suggestion: ReplayScannerPromptSuggestionApi
    isDarkModeOn: boolean
}): JSX.Element {
    const [isDiffExpanded, setIsDiffExpanded] = useState(false)
    if (!suggestion.base_prompt) {
        return (
            <div className="border rounded bg-surface-secondary p-2 font-mono text-xs whitespace-pre-wrap max-h-48 overflow-y-auto">
                {suggestion.suggested_prompt}
            </div>
        )
    }
    return (
        <>
            <SuggestionDiffPanes
                suggestion={suggestion}
                beforeLabel="Current prompt"
                isDarkModeOn={isDarkModeOn}
                onExpand={() => setIsDiffExpanded(true)}
            />
            <LemonModal
                isOpen={isDiffExpanded}
                onClose={() => setIsDiffExpanded(false)}
                title="Recommendation"
                fullScreen
            >
                <div className="space-y-4">
                    <SuggestionDiffPanes
                        suggestion={suggestion}
                        beforeLabel="Current prompt"
                        isDarkModeOn={isDarkModeOn}
                        editorHeight="calc(100vh - 16rem)"
                    />
                    {suggestion.rationale && (
                        <div>
                            <h4 className="text-sm font-semibold m-0 mb-1">Why</h4>
                            <p className="text-sm text-muted m-0">{suggestion.rationale}</p>
                        </div>
                    )}
                </div>
            </LemonModal>
        </>
    )
}

const TAG_OP_TAG_TYPE: Record<ScannerConfigChange['op'], LemonTagType> = {
    add: 'success',
    remove: 'danger',
    rename: 'default',
    set: 'default',
}

function TagChangesCard({ changes }: { changes: ScannerConfigChange[] }): JSX.Element {
    return (
        <div className="space-y-1.5">
            <h4 className="text-xs font-semibold text-muted m-0">Tag changes</h4>
            <div className="flex flex-wrap gap-1">
                {changes.map((change, index) => (
                    <LemonTag key={index} type={TAG_OP_TAG_TYPE[change.op]}>
                        {describeTagOp(change).text}
                    </LemonTag>
                ))}
            </div>
            {changes.map(
                (change, index) =>
                    change.rationale && (
                        <p key={index} className="text-xs text-muted m-0">
                            {change.rationale}
                        </p>
                    )
            )}
        </div>
    )
}

function FieldChangeLine({ change }: { change: ScannerConfigChange }): JSX.Element {
    return (
        <div className="border rounded p-2 space-y-1">
            <div className="text-sm">
                <span className="font-medium">{identifierToHuman(change.field)}</span>:{' '}
                {formatChangeValue(change.before)} to {formatChangeValue(change.after)}
            </div>
            {change.rationale && <p className="text-xs text-muted m-0">{change.rationale}</p>}
        </div>
    )
}

/** Renders one card per kind of change a recommendation makes: prompt diff, tag vocabulary, and scalar config fields. */
export function ConfigChangeCards({
    suggestion,
    isDarkModeOn,
}: {
    suggestion: ReplayScannerPromptSuggestionApi
    isDarkModeOn: boolean
}): JSX.Element {
    const changes = parseConfigChanges(suggestion.changes)
    const promptChange = changes.find((change) => change.kind === 'prompt')
    const tagChanges = changes.filter((change) => change.kind === 'tags')
    const fieldChanges = changes.filter((change) => change.kind !== 'prompt' && change.kind !== 'tags')
    // Suggestions from before this field existed have an empty changes list, and a change list could in
    // principle omit a real prompt rewrite, so fall back to diffing the stored prompts directly.
    const showPromptFallback = !promptChange && suggestion.base_prompt !== suggestion.suggested_prompt

    return (
        <div className="space-y-3">
            {(promptChange || showPromptFallback) && (
                <PromptChangeCard suggestion={suggestion} isDarkModeOn={isDarkModeOn} />
            )}
            {tagChanges.length > 0 && <TagChangesCard changes={tagChanges} />}
            {fieldChanges.map((change, index) => (
                <FieldChangeLine key={`${change.field}-${index}`} change={change} />
            ))}
        </div>
    )
}
