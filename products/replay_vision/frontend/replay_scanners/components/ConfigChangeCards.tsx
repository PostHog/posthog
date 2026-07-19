import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconExpand45, IconRevert } from '@posthog/icons'
import {
    LemonButton,
    LemonInput,
    LemonModal,
    LemonSegmentedButton,
    LemonSwitch,
    LemonTag,
    LemonTagType,
    LemonTextArea,
} from '@posthog/lemon-ui'

import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { identifierToHuman } from 'lib/utils/strings'

import type { ReplayScannerPromptSuggestionApi } from '../../generated/api.schemas'
import { scannerQualityLogic } from '../scannerQualityLogic'
import { SummarizerScannerConfig } from '../types'
import {
    changedFields,
    describeTagOp,
    formatChangeValue,
    parseConfigChanges,
    ScannerConfigChange,
} from './configChanges'
import { SUMMARIZER_LENGTH_OPTIONS } from './ScannerTypeConfigEditor'

/** The bordered side-by-side diff with labeled panes, rendered inline and inside the fullscreen modal. */
function SuggestionDiffPanes({
    original,
    modified,
    isDarkModeOn,
    editorHeight,
    onExpand,
}: {
    original: string | null
    modified: string | null
    isDarkModeOn: boolean
    editorHeight?: string
    onExpand?: () => void
}): JSX.Element {
    return (
        <div className="border rounded overflow-hidden">
            <div className="flex items-center border-b bg-surface-secondary text-xs font-medium">
                <div className="flex-1 px-3 py-1.5 border-r">Current prompt</div>
                <div className="flex-1 px-3 py-1.5 flex items-center justify-between">
                    <span>New prompt</span>
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
                original={original}
                modified={modified}
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

/** The current-vs-new prompt diff, expandable to full screen. Its right pane reflects the edited value live. */
function PromptDiff({
    original,
    modified,
    isDarkModeOn,
}: {
    original: string | null
    modified: string | null
    isDarkModeOn: boolean
}): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(false)
    return (
        <>
            <SuggestionDiffPanes
                original={original}
                modified={modified}
                isDarkModeOn={isDarkModeOn}
                onExpand={() => setIsExpanded(true)}
            />
            <LemonModal isOpen={isExpanded} onClose={() => setIsExpanded(false)} title="Recommendation" fullScreen>
                <SuggestionDiffPanes
                    original={original}
                    modified={modified}
                    isDarkModeOn={isDarkModeOn}
                    editorHeight="calc(100vh - 16rem)"
                />
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

/** Read-only hint of the tag adds and removes the AI proposed, above the editable tag list. */
function TagChips({ changes }: { changes: ScannerConfigChange[] }): JSX.Element {
    return (
        <div className="flex flex-wrap gap-1">
            {changes.map((change, index) => (
                <LemonTag key={index} type={TAG_OP_TAG_TYPE[change.op]}>
                    {describeTagOp(change).text}
                </LemonTag>
            ))}
        </div>
    )
}

/** The editable control for a field, by kind. */
function FieldValueEditor({
    kind,
    value,
    onChange,
    basePrompt,
    isDarkModeOn,
    tagChanges,
}: {
    kind: ScannerConfigChange['kind']
    value: unknown
    onChange: (value: unknown) => void
    basePrompt: string | null
    isDarkModeOn: boolean
    tagChanges: ScannerConfigChange[]
}): JSX.Element {
    if (kind === 'prompt') {
        return (
            <div className="space-y-2">
                {basePrompt ? (
                    <PromptDiff original={basePrompt} modified={String(value ?? '')} isDarkModeOn={isDarkModeOn} />
                ) : null}
                <LemonTextArea value={String(value ?? '')} onChange={onChange} minRows={6} />
            </div>
        )
    }
    if (kind === 'tags') {
        const tags = (value as string[]) ?? []
        return (
            <div className="space-y-2">
                <TagChips changes={tagChanges} />
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    placeholder="Type a tag and press enter..."
                    value={tags}
                    onChange={onChange}
                    options={tags.map((t) => ({ key: t, label: t }))}
                />
            </div>
        )
    }
    if (kind === 'scale') {
        const scale = (value as { min: number; max: number; label?: string }) ?? { min: 0, max: 10 }
        return (
            <div className="space-y-2">
                <div className="flex items-center gap-3 max-w-md">
                    <LemonInput
                        type="number"
                        value={Number.isFinite(scale.min) ? scale.min : undefined}
                        onChange={(v) => onChange({ ...scale, min: v ?? Number.NaN })}
                        prefix={<span className="text-muted text-xs">min</span>}
                    />
                    <span className="text-muted">to</span>
                    <LemonInput
                        type="number"
                        value={Number.isFinite(scale.max) ? scale.max : undefined}
                        onChange={(v) => onChange({ ...scale, max: v ?? Number.NaN })}
                        prefix={<span className="text-muted text-xs">max</span>}
                    />
                </div>
                <LemonInput
                    value={scale.label ?? ''}
                    onChange={(v) => onChange({ ...scale, label: v || undefined })}
                    placeholder="Score label (optional)"
                />
            </div>
        )
    }
    if (kind === 'length') {
        return (
            <LemonSegmentedButton
                options={SUMMARIZER_LENGTH_OPTIONS}
                value={value as SummarizerScannerConfig['length']}
                onChange={onChange}
            />
        )
    }
    // flag: a plain on/off toggle for the boolean field.
    return <LemonSwitch checked={!!value} onChange={onChange} label={value ? 'On' : 'Off'} />
}

/** The static before-to-after view of a field, used for past recommendations. */
function FieldValueReadOnly({
    kind,
    suggestion,
    isDarkModeOn,
    fieldChanges,
}: {
    kind: ScannerConfigChange['kind']
    suggestion: ReplayScannerPromptSuggestionApi
    isDarkModeOn: boolean
    fieldChanges: ScannerConfigChange[]
}): JSX.Element {
    if (kind === 'prompt') {
        return suggestion.base_prompt ? (
            <PromptDiff
                original={suggestion.base_prompt}
                modified={suggestion.suggested_prompt}
                isDarkModeOn={isDarkModeOn}
            />
        ) : (
            <div className="border rounded bg-surface-secondary p-2 font-mono text-xs whitespace-pre-wrap max-h-48 overflow-y-auto">
                {suggestion.suggested_prompt}
            </div>
        )
    }
    if (kind === 'tags') {
        return <TagChips changes={fieldChanges} />
    }
    const change = fieldChanges[0]
    return (
        <div className="text-sm">
            {formatChangeValue(change?.before)} to {formatChangeValue(change?.after)}
        </div>
    )
}

/** One recommendation. For the current suggestion every changed field is editable, so the user controls the new
 *  version (a field edited back to its current value is a no-op). Past recommendations render read-only. */
export function ConfigChangeCards({
    suggestion,
    isDarkModeOn,
    scannerId,
    readOnly = false,
}: {
    suggestion: ReplayScannerPromptSuggestionApi
    isDarkModeOn: boolean
    scannerId: string
    readOnly?: boolean
}): JSX.Element {
    const { fieldValues } = useValues(scannerQualityLogic({ scannerId }))
    const { setFieldValue } = useActions(scannerQualityLogic({ scannerId }))
    const changes = parseConfigChanges(suggestion.changes)
    const fields = changedFields(changes)
    const base = (suggestion.base_config ?? {}) as Record<string, unknown>
    const suggested = (suggestion.suggested_config ?? {}) as Record<string, unknown>

    // Rows written before changes[] existed carry no fields but may still rewrite the prompt.
    if (fields.length === 0) {
        return suggestion.base_prompt !== suggestion.suggested_prompt ? (
            <PromptDiff
                original={suggestion.base_prompt}
                modified={suggestion.suggested_prompt}
                isDarkModeOn={isDarkModeOn}
            />
        ) : (
            <></>
        )
    }

    return (
        <div className="space-y-3">
            {fields.map(({ field, kind }) => {
                const fieldChanges = changes.filter((change) => change.field === field)
                const suggestedValue = suggested[field] ?? base[field]
                const value = readOnly ? suggestedValue : fieldValues[field]
                const edited = !readOnly && JSON.stringify(value) !== JSON.stringify(suggestedValue)
                return (
                    <div key={field} className="border rounded p-2 space-y-2">
                        <div className="flex items-center justify-between">
                            <span className="text-sm font-medium">{identifierToHuman(field)}</span>
                            {edited && (
                                <LemonButton
                                    size="xsmall"
                                    type="secondary"
                                    icon={<IconRevert />}
                                    onClick={() => setFieldValue(field, suggestedValue)}
                                    tooltip="Revert to the suggested value"
                                    data-attr="vision-quality-revert-field"
                                >
                                    Revert
                                </LemonButton>
                            )}
                        </div>
                        {readOnly ? (
                            <FieldValueReadOnly
                                kind={kind}
                                suggestion={suggestion}
                                isDarkModeOn={isDarkModeOn}
                                fieldChanges={fieldChanges}
                            />
                        ) : (
                            <FieldValueEditor
                                kind={kind}
                                value={value}
                                onChange={(newValue) => setFieldValue(field, newValue)}
                                basePrompt={suggestion.base_prompt}
                                isDarkModeOn={isDarkModeOn}
                                tagChanges={fieldChanges}
                            />
                        )}
                        {fieldChanges.map(
                            (change, index) =>
                                change.rationale && (
                                    <p key={index} className="text-xs text-muted m-0">
                                        {change.rationale}
                                    </p>
                                )
                        )}
                    </div>
                )
            })}
        </div>
    )
}
