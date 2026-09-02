import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconPencil, IconRevert } from '@posthog/icons'
import {
    LemonCard,
    LemonInput,
    LemonSegmentedButton,
    LemonTag,
    LemonTagType,
    LemonTextArea,
    Tooltip,
} from '@posthog/lemon-ui'

import { objectsEqual } from 'lib/utils/objects'

import { BooleanTag } from '../../components/BooleanTag'
import { CardHeader } from '../../components/CardHeader'
import type { ReplayScannerPromptSuggestionApi } from '../../generated/api.schemas'
import { replayScannerLogic } from '../replayScannerLogic'
import { scannerCalibrationLogic } from '../scannerCalibrationLogic'
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
import { PromptDiff } from './PromptDiff'
import { SUMMARIZER_LENGTH_OPTIONS } from './ScannerTypeConfigEditor'

const TAG_OP_TAG_TYPE: Record<ScannerConfigChange['op'], LemonTagType> = {
    add: 'success',
    remove: 'danger',
    rename: 'default',
    set: 'default',
}

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

/** Editable tag vocabulary: each candidate is a clickable chip, greyed out when not in the new vocabulary. */
function EditableTags({
    candidates,
    value,
    onChange,
}: {
    candidates: string[]
    value: string[]
    onChange: (tags: string[]) => void
}): JSX.Element {
    const [draft, setDraft] = useState('')
    const selected = new Set(value)
    const allTags = [...new Set([...candidates, ...value])]
    const toggle = (tag: string): void => onChange(selected.has(tag) ? value.filter((t) => t !== tag) : [...value, tag])
    const addDraft = (): void => {
        const tag = draft.trim()
        if (tag && !value.includes(tag)) {
            onChange([...value, tag])
        }
        setDraft('')
    }
    return (
        <div className="flex flex-wrap items-center gap-1">
            {allTags.map((tag) => {
                const isSelected = selected.has(tag)
                return (
                    <LemonTag
                        key={tag}
                        type={isSelected ? 'option' : 'default'}
                        onClick={() => toggle(tag)}
                        className={isSelected ? 'cursor-pointer' : 'cursor-pointer opacity-50 line-through'}
                    >
                        {tag}
                    </LemonTag>
                )
            })}
            <LemonInput
                size="xsmall"
                value={draft}
                onChange={setDraft}
                onPressEnter={addDraft}
                onBlur={addDraft}
                placeholder="Add category…"
                className="w-24 [&_input]:placeholder:text-tertiary [&_input]:placeholder:text-xs"
            />
        </div>
    )
}

function FieldValueEditor({
    kind,
    value,
    onChange,
    basePrompt,
    isDarkModeOn,
    tagCandidates = [],
}: {
    kind: FieldEditorKind
    value: unknown
    onChange: (value: unknown) => void
    basePrompt: string | null
    isDarkModeOn: boolean
    tagCandidates?: string[]
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
        return <EditableTags candidates={tagCandidates} value={(value as string[]) ?? []} onChange={onChange} />
    }
    if (kind === 'scale') {
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
                className="max-w-full overflow-x-auto"
                options={SUMMARIZER_LENGTH_OPTIONS}
                value={value as SummarizerScannerConfig['length']}
                onChange={onChange}
            />
        )
    }
    if (kind === 'flag') {
        return <BooleanTag value={!!value} onClick={() => onChange(!value)} />
    }
    return <LemonTextArea value={String(value ?? '')} onChange={onChange} minRows={2} />
}

/** A config field's value, read-only. Shared with the config-versions history so both read the same. */
export function FieldCurrentValue({ kind, value }: { kind: FieldEditorKind; value: unknown }): JSX.Element {
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

/** The read-only before-to-after view of a field, used for past recommendations. */
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

/** A field's change rationales, deduplicated since several tag ops often share one. */
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

/** One recommendation as a Current-to-New comparison: every configurable field is editable, so the user
 *  controls the new version. Past recommendations render their changes read-only. */
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
    const { fieldValues } = useValues(scannerCalibrationLogic({ scannerId }))
    const { setFieldValue } = useActions(scannerCalibrationLogic({ scannerId }))
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

    const fieldNames = Object.keys(suggested).sort((a, b) => (a === 'prompt' ? -1 : b === 'prompt' ? 1 : 0))
    const structuredFields = fieldNames.filter((field) => field !== 'prompt')

    const fieldLabelText = (field: string): string => {
        const { label } = fieldEditor(field, fieldValues[field])
        return field === 'prompt' && scanner?.scanner_type === 'summarizer' ? 'Additional context' : label
    }

    // Restores the AI's suggestion after the user has overwritten it. Absolutely positioned so it stays out
    // of the layout: rows keep their height and the columns stay aligned whether it shows or not.
    const revertButton = (field: string): JSX.Element | null =>
        objectsEqual(fieldValues[field], suggested[field]) ? null : (
            <Tooltip title="Revert to the suggested value">
                <button
                    type="button"
                    aria-label="Revert to the suggested value"
                    data-attr="vision-calibration-revert-field"
                    onClick={() => setFieldValue(suggestion.id, field, suggested[field])}
                    className="absolute top-0 right-0 flex cursor-pointer text-muted hover:text-default"
                >
                    <IconRevert />
                </button>
            </Tooltip>
        )

    return (
        <LemonCard className="p-4" hoverEffect={false}>
            <CardHeader icon={<IconPencil />} title="Behavior" />
            <div className="flex flex-col gap-4">
                {fieldNames.includes('prompt') && (
                    <div className="relative">
                        <div className="text-xs text-muted mb-1">{fieldLabelText('prompt')}</div>
                        <FieldValueEditor
                            kind="prompt"
                            value={fieldValues.prompt}
                            onChange={(newValue) => setFieldValue(suggestion.id, 'prompt', newValue)}
                            basePrompt={suggestion.base_prompt}
                            isDarkModeOn={isDarkModeOn}
                        />
                        <FieldRationales fieldChanges={changes.filter((change) => change.field === 'prompt')} />
                        {revertButton('prompt')}
                    </div>
                )}
                {structuredFields.length > 0 && (
                    <div className="relative flex flex-col gap-4">
                        <div className="hidden sm:block absolute inset-y-4 left-1/2 border-l" aria-hidden />
                        <div className="hidden sm:grid grid-cols-2 gap-10 text-xs font-medium text-muted">
                            <span>Current</span>
                            <span>New</span>
                        </div>
                        {structuredFields.map((field) => {
                            const { kind } = fieldEditor(field, fieldValues[field])
                            const label = fieldLabelText(field)
                            const candidates =
                                kind === 'tags'
                                    ? [...((base[field] as string[]) ?? []), ...((suggested[field] as string[]) ?? [])]
                                    : []
                            return (
                                <div
                                    key={field}
                                    className="grid grid-cols-1 gap-2 sm:grid-cols-2 sm:gap-10 items-start"
                                >
                                    <div>
                                        <div className="text-xs text-muted mb-1">{label}</div>
                                        <FieldCurrentValue kind={kind} value={base[field]} />
                                    </div>
                                    <div className="relative">
                                        <div className="text-xs text-muted mb-1">{label}</div>
                                        <FieldValueEditor
                                            kind={kind}
                                            value={fieldValues[field]}
                                            onChange={(newValue) => setFieldValue(suggestion.id, field, newValue)}
                                            basePrompt={suggestion.base_prompt}
                                            isDarkModeOn={isDarkModeOn}
                                            tagCandidates={candidates}
                                        />
                                        <FieldRationales
                                            fieldChanges={changes.filter((change) => change.field === field)}
                                        />
                                        {revertButton(field)}
                                    </div>
                                </div>
                            )
                        })}
                    </div>
                )}
            </div>
        </LemonCard>
    )
}
