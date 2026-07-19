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
import { objectsEqual } from 'lib/utils/objects'

import type { ReplayScannerPromptSuggestionApi } from '../../generated/api.schemas'
import { replayScannerLogic } from '../replayScannerLogic'
import { scannerQualityLogic } from '../scannerQualityLogic'
import { SummarizerScannerConfig } from '../types'
import {
    changedFields,
    describeTagOp,
    fieldEditor,
    FieldEditorKind,
    formatChangeValue,
    parseConfigChanges,
    ScannerConfigChange,
} from './configChanges'
import { SUMMARIZER_LENGTH_OPTIONS } from './ScannerTypeConfigEditor'

/** The bordered side-by-side prompt diff. When editable, the right pane is the prompt editor. */
function SuggestionDiffPanes({
    original,
    modified,
    onChange,
    editable,
    isDarkModeOn,
    editorHeight,
    onExpand,
}: {
    original: string | null
    modified: string | null
    onChange?: (value: string) => void
    editable?: boolean
    isDarkModeOn: boolean
    editorHeight?: string
    onExpand?: () => void
}): JSX.Element {
    return (
        <div className="border rounded overflow-hidden">
            <div className="flex items-center border-b bg-surface-secondary text-xs font-medium">
                <div className="flex-1 px-3 py-1.5 border-r">Current prompt</div>
                <div className="flex-1 px-3 py-1.5 flex items-center justify-between">
                    <span>{editable ? 'New prompt (edit directly)' : 'New prompt'}</span>
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
                onChange={onChange ? (value) => onChange(value) : undefined}
                modifiedEditable={editable}
                language="markdown"
                theme={isDarkModeOn ? 'vs-dark' : 'vs-light'}
                height={editorHeight}
                options={{
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

/** The prompt diff, expandable to full screen. Edits in either instance flow through the same onChange. */
function PromptDiff({
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
    return (
        <>
            <SuggestionDiffPanes
                original={original}
                modified={modified}
                onChange={onChange}
                editable={editable}
                isDarkModeOn={isDarkModeOn}
                onExpand={() => setIsExpanded(true)}
            />
            <LemonModal isOpen={isExpanded} onClose={() => setIsExpanded(false)} title="Recommendation" fullScreen>
                <SuggestionDiffPanes
                    original={original}
                    modified={modified}
                    onChange={onChange}
                    editable={editable}
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

/** The editable control for a config field, by kind. */
function FieldValueEditor({
    kind,
    value,
    onChange,
    basePrompt,
    isDarkModeOn,
    tagChanges,
}: {
    kind: FieldEditorKind
    value: unknown
    onChange: (value: unknown) => void
    basePrompt: string | null
    isDarkModeOn: boolean
    tagChanges: ScannerConfigChange[]
}): JSX.Element {
    if (kind === 'prompt') {
        if (!basePrompt) {
            return <LemonTextArea value={String(value ?? '')} onChange={onChange} minRows={6} />
        }
        return (
            <PromptDiff
                original={basePrompt}
                modified={String(value ?? '')}
                onChange={onChange}
                editable
                isDarkModeOn={isDarkModeOn}
            />
        )
    }
    if (kind === 'tags') {
        const tags = (value as string[]) ?? []
        return (
            <div className="space-y-2">
                {tagChanges.length > 0 && <TagChips changes={tagChanges} />}
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
        // Mirrors the scale editor in ScannerTypeConfigEditor.
        const scale = (value as { min: number; max: number; label?: string }) ?? { min: 0, max: 10 }
        return (
            <div className="space-y-3">
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
                <div className="space-y-1">
                    <label className="block text-sm font-medium">Score label (optional)</label>
                    <LemonInput
                        value={scale.label ?? ''}
                        onChange={(v) => onChange({ ...scale, label: v || undefined })}
                        placeholder="frustration"
                    />
                </div>
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
    return <LemonTextArea value={String(value ?? '')} onChange={onChange} minRows={2} />
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

/** The rationales behind a field's changes, deduplicated (several tag ops often share one). */
function FieldRationales({ fieldChanges }: { fieldChanges: ScannerConfigChange[] }): JSX.Element {
    return (
        <>
            {[...new Set(fieldChanges.map((change) => change.rationale).filter(Boolean))].map((rationale) => (
                <p key={rationale} className="text-xs text-muted m-0">
                    {rationale}
                </p>
            ))}
        </>
    )
}

/** One recommendation. The current suggestion renders every configurable field as an editor seeded with the
 *  AI's suggestion, so the user controls exactly what the new version will be (editing everything back to the
 *  current config makes applying a no-op). Past recommendations render only their changes, read-only. */
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
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))
    const changes = parseConfigChanges(suggestion.changes)

    // Rows written before changes[] existed only carry a prompt rewrite, with no full config to edit.
    if (changes.length === 0) {
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

    const base = (suggestion.base_config ?? {}) as Record<string, unknown>
    const suggested = { ...base, ...((suggestion.suggested_config ?? {}) as Record<string, unknown>) }
    const fieldNames = readOnly
        ? changedFields(changes).map(({ field }) => field)
        : Object.keys(suggested).sort((a, b) => (a === 'prompt' ? -1 : b === 'prompt' ? 1 : 0))

    return (
        <div className="space-y-4">
            {fieldNames.map((field) => {
                const fieldChanges = changes.filter((change) => change.field === field)
                const value = readOnly ? suggested[field] : fieldValues[field]
                const { kind, label, description } = fieldEditor(field, value)
                // The configurator labels the summarizer's prompt "Additional context"; read the same way here.
                const fieldLabel =
                    field === 'prompt' && scanner?.scanner_type === 'summarizer' ? 'Additional context' : label
                const edited = !readOnly && !objectsEqual(value, suggested[field])
                const revert = edited ? (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconRevert />}
                        onClick={() => setFieldValue(suggestion.id, field, suggested[field])}
                        tooltip="Revert to the suggested value"
                        data-attr="vision-quality-revert-field"
                    >
                        Revert
                    </LemonButton>
                ) : null

                // Flags render as the configurator's switch rows: switch left, title and description beside it.
                if (kind === 'flag' && !readOnly) {
                    return (
                        <div key={field} className="space-y-1">
                            <div className="flex items-center justify-between gap-2">
                                <div className="flex items-center gap-2">
                                    <LemonSwitch
                                        checked={!!value}
                                        onChange={(checked) => setFieldValue(suggestion.id, field, checked)}
                                    />
                                    <div>
                                        <div className="text-sm font-medium">{fieldLabel}</div>
                                        {description && <div className="text-xs text-muted">{description}</div>}
                                    </div>
                                </div>
                                {revert}
                            </div>
                            <FieldRationales fieldChanges={fieldChanges} />
                        </div>
                    )
                }

                return (
                    <div key={field} className="space-y-2">
                        <div className="flex items-center justify-between gap-2">
                            <label className="text-sm font-medium">{fieldLabel}</label>
                            {revert}
                        </div>
                        {readOnly ? (
                            <FieldValueReadOnly
                                kind={kind as ScannerConfigChange['kind']}
                                suggestion={suggestion}
                                isDarkModeOn={isDarkModeOn}
                                fieldChanges={fieldChanges}
                            />
                        ) : (
                            <FieldValueEditor
                                kind={kind}
                                value={value}
                                onChange={(newValue) => setFieldValue(suggestion.id, field, newValue)}
                                basePrompt={suggestion.base_prompt}
                                isDarkModeOn={isDarkModeOn}
                                tagChanges={fieldChanges}
                            />
                        )}
                        <FieldRationales fieldChanges={fieldChanges} />
                    </div>
                )
            })}
        </div>
    )
}
