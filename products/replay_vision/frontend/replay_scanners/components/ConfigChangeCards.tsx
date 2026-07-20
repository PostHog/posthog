import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconExpand45, IconPencil, IconRevert } from '@posthog/icons'
import {
    LemonButton,
    LemonCard,
    LemonInput,
    LemonModal,
    LemonSegmentedButton,
    LemonSwitch,
    LemonTag,
    LemonTagType,
    LemonTextArea,
} from '@posthog/lemon-ui'

import MonacoDiffEditor from 'lib/components/MonacoDiffEditor'
import { objectsEqual } from 'lib/utils/objects'

import { BooleanTag } from '../../components/BooleanTag'
import { CardHeader } from '../../components/CardHeader'
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

/** Editable tag list that renders the same `option` chips as the current-config column, plus an inline add. */
function EditableTags({ value, onChange }: { value: string[]; onChange: (tags: string[]) => void }): JSX.Element {
    const [draft, setDraft] = useState('')
    const tags = value ?? []
    const addDraft = (): void => {
        const tag = draft.trim()
        if (tag && !tags.includes(tag)) {
            onChange([...tags, tag])
        }
        setDraft('')
    }
    return (
        <div className="flex flex-wrap items-center gap-1">
            {tags.map((tag) => (
                <LemonTag key={tag} type="option" closable onClose={() => onChange(tags.filter((t) => t !== tag))}>
                    {tag}
                </LemonTag>
            ))}
            <LemonInput
                size="small"
                value={draft}
                onChange={setDraft}
                onPressEnter={addDraft}
                onBlur={addDraft}
                placeholder="Add tag…"
                className="w-28"
            />
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
}: {
    kind: FieldEditorKind
    value: unknown
    onChange: (value: unknown) => void
    basePrompt: string | null
    isDarkModeOn: boolean
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
        return <EditableTags value={(value as string[]) ?? []} onChange={onChange} />
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
    if (kind === 'flag') {
        return <LemonSwitch checked={!!value} onChange={onChange} label={value ? 'Enabled' : 'Disabled'} />
    }
    return <LemonTextArea value={String(value ?? '')} onChange={onChange} minRows={2} />
}

/** The read-only rendering of a field's current value, shown in the "Current" column beside its editor. */
function FieldCurrentValue({ kind, value }: { kind: FieldEditorKind; value: unknown }): JSX.Element {
    if (kind === 'tags') {
        const tags = (value as string[]) ?? []
        return tags.length ? (
            <div className="flex flex-wrap gap-1">
                {tags.map((tag) => (
                    <LemonTag key={tag} type="option">
                        {tag}
                    </LemonTag>
                ))}
            </div>
        ) : (
            <span className="text-muted text-sm">—</span>
        )
    }
    if (kind === 'flag') {
        return <BooleanTag value={!!value} />
    }
    if (kind === 'scale') {
        const scale = value as { min?: number; max?: number; label?: string } | undefined
        return <span className="text-sm">{formatChangeValue(scale)}</span>
    }
    if (kind === 'length') {
        return (
            <span className="text-sm">
                {SUMMARIZER_LENGTH_OPTIONS.find((option) => option.value === value)?.label ?? String(value ?? '—')}
            </span>
        )
    }
    return <span className="text-sm whitespace-pre-wrap">{String(value ?? '') || '—'}</span>
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

    // Past recommendations sit inside a history card and only recap their changes, read-only.
    if (readOnly) {
        return (
            <div className="flex flex-col gap-3">
                {changedFields(changes).map(({ field, kind }) => {
                    const fieldChanges = changes.filter((change) => change.field === field)
                    return (
                        <div key={field}>
                            <div className="text-xs text-muted mb-0.5">
                                {fieldEditor(field, suggested[field]).label}
                            </div>
                            <FieldValueReadOnly
                                kind={kind}
                                suggestion={suggestion}
                                isDarkModeOn={isDarkModeOn}
                                fieldChanges={fieldChanges}
                            />
                            <FieldRationales fieldChanges={fieldChanges} />
                        </div>
                    )
                })}
            </div>
        )
    }

    // The prompt is a full-width current-vs-new diff; the remaining fields sit in Current | New columns.
    const fieldNames = Object.keys(suggested).sort((a, b) => (a === 'prompt' ? -1 : b === 'prompt' ? 1 : 0))
    const structuredFields = fieldNames.filter((field) => field !== 'prompt')

    // Rendered even when not edited (invisible) so the row height never changes as it appears or disappears.
    const revertButton = (field: string, edited: boolean): JSX.Element => (
        <LemonButton
            size="xsmall"
            type="secondary"
            icon={<IconRevert />}
            onClick={() => setFieldValue(suggestion.id, field, suggested[field])}
            tooltip="Revert to the suggested value"
            data-attr="vision-quality-revert-field"
            className={edited ? undefined : 'invisible'}
            aria-hidden={!edited}
        >
            Revert
        </LemonButton>
    )

    const fieldLabelText = (field: string): string => {
        const { label } = fieldEditor(field, fieldValues[field])
        return field === 'prompt' && scanner?.scanner_type === 'summarizer' ? 'Additional context' : label
    }

    return (
        <LemonCard className="p-4" hoverEffect={false}>
            <CardHeader icon={<IconPencil />} title="Behavior" />
            <div className="flex flex-col gap-4">
                {fieldNames.includes('prompt') && (
                    <div>
                        <div className="flex items-center justify-between gap-2 mb-1">
                            <span className="text-xs text-muted">{fieldLabelText('prompt')}</span>
                            {revertButton('prompt', !objectsEqual(fieldValues.prompt, suggested.prompt))}
                        </div>
                        <FieldValueEditor
                            kind="prompt"
                            value={fieldValues.prompt}
                            onChange={(newValue) => setFieldValue(suggestion.id, 'prompt', newValue)}
                            basePrompt={suggestion.base_prompt}
                            isDarkModeOn={isDarkModeOn}
                        />
                        <FieldRationales fieldChanges={changes.filter((change) => change.field === 'prompt')} />
                    </div>
                )}
                {structuredFields.length > 0 && (
                    <div className="relative flex flex-col gap-3">
                        {/* A quiet divider down the middle to separate the current and new columns. */}
                        <div className="absolute inset-y-0 left-1/2 border-l" aria-hidden />
                        <div className="grid grid-cols-2 gap-3 text-xs font-medium text-muted border-b pb-1">
                            <span>Current</span>
                            <span>New</span>
                        </div>
                        {structuredFields.map((field) => {
                            const { kind } = fieldEditor(field, fieldValues[field])
                            const edited = !objectsEqual(fieldValues[field], suggested[field])
                            return (
                                <div key={field}>
                                    <div className="flex items-center justify-between gap-2 mb-1">
                                        <span className="text-xs text-muted">{fieldLabelText(field)}</span>
                                        {revertButton(field, edited)}
                                    </div>
                                    <div className="grid grid-cols-2 gap-3 items-start">
                                        <div>
                                            <FieldCurrentValue kind={kind} value={base[field]} />
                                        </div>
                                        <div>
                                            <FieldValueEditor
                                                kind={kind}
                                                value={fieldValues[field]}
                                                onChange={(newValue) => setFieldValue(suggestion.id, field, newValue)}
                                                basePrompt={suggestion.base_prompt}
                                                isDarkModeOn={isDarkModeOn}
                                            />
                                        </div>
                                    </div>
                                    <FieldRationales
                                        fieldChanges={changes.filter((change) => change.field === field)}
                                    />
                                </div>
                            )
                        })}
                    </div>
                )}
            </div>
        </LemonCard>
    )
}
