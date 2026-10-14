import { useId, useState } from 'react'

import { IconChevronDown, IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonInput, LemonSwitch, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { cn } from 'lib/utils/css-classes'

import type { ScoutRubricCriterionApi } from 'products/signals/frontend/generated/api.schemas'

export function ScoutRubricCriterionEditor({
    criterion,
    expanded,
    saving,
    selected,
    onSelect,
    onChange,
    onExpand,
    onRemove,
}: {
    criterion: ScoutRubricCriterionApi
    expanded: boolean
    saving: boolean
    selected?: boolean
    onSelect?: (selected: boolean) => void
    onChange: (changes: Partial<ScoutRubricCriterionApi>) => void
    onExpand: () => void
    onRemove: () => void
}): JSX.Element {
    const [detailsExpanded, setDetailsExpanded] = useState(false)
    const detailsId = useId()
    const disabledReason = saving ? 'Saving rubrics' : undefined
    const isSuggestion = onSelect !== undefined
    const title = criterion.title || 'New criterion'
    const detailsLabel = `${detailsExpanded ? 'Hide details' : 'Show details'} for ${title}`

    return (
        <div
            className={cn(
                'grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-x-3 gap-y-2 px-4 py-3 transition-colors motion-reduce:transition-none',
                isSuggestion && selected && 'bg-accent-highlight-secondary'
            )}
        >
            <div className="pt-0.5">
                {isSuggestion ? (
                    <LemonCheckbox
                        checked={selected}
                        onChange={onSelect}
                        disabledReason={disabledReason}
                        aria-label={`Select ${title}`}
                        data-attr="scout-rubric-select-suggestion"
                    />
                ) : (
                    <LemonSwitch
                        checked={criterion.enabled}
                        onChange={(enabled) => onChange({ enabled })}
                        disabledReason={disabledReason}
                        aria-label={`Enable ${title}`}
                        data-attr="scout-rubric-enable"
                    />
                )}
            </div>
            {expanded ? (
                <div className="col-span-2 flex min-w-0 flex-col gap-3">
                    <LemonField.Pure label="Title" htmlFor={`${criterion.id}-title`}>
                        <LemonInput
                            id={`${criterion.id}-title`}
                            value={criterion.title}
                            maxLength={120}
                            onChange={(title) => onChange({ title })}
                            disabledReason={disabledReason}
                            placeholder="e.g. Check the affected time window"
                            data-attr="scout-rubric-title"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Description" htmlFor={`${criterion.id}-description`}>
                        <LemonTextArea
                            id={`${criterion.id}-description`}
                            value={criterion.description}
                            onChange={(description) => onChange({ description })}
                            minRows={2}
                            maxLength={1000}
                            disabled={saving}
                            data-attr="scout-rubric-description"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Passes when" htmlFor={`${criterion.id}-pass`}>
                        <LemonTextArea
                            id={`${criterion.id}-pass`}
                            value={criterion.pass_condition}
                            onChange={(pass_condition) => onChange({ pass_condition })}
                            minRows={2}
                            maxLength={2000}
                            disabled={saving}
                            data-attr="scout-rubric-pass-condition"
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Applies to" htmlFor={`${criterion.id}-applicability`}>
                        <LemonTextArea
                            id={`${criterion.id}-applicability`}
                            value={criterion.applicability}
                            onChange={(applicability) => onChange({ applicability })}
                            minRows={1}
                            maxLength={1000}
                            disabled={saving}
                            data-attr="scout-rubric-applicability"
                        />
                    </LemonField.Pure>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                        <p className="mb-0 min-w-0 flex-1 basis-52 text-sm text-secondary">
                            {isSuggestion
                                ? 'Editing selects this suggestion. Use Save rubrics to add it to this scout.'
                                : criterion.source === 'default'
                                  ? 'Changes to this default apply to this scout only. Use Save rubrics to save them.'
                                  : 'Use Save rubrics to save these changes.'}
                        </p>
                        <LemonButton
                            type="secondary"
                            size="small"
                            onClick={onExpand}
                            disabledReason={disabledReason}
                            data-attr="scout-rubric-done-editing"
                        >
                            Done editing
                        </LemonButton>
                    </div>
                </div>
            ) : (
                <>
                    <div className={cn('min-w-0', !isSuggestion && !criterion.enabled && 'opacity-60')}>
                        <div className="flex flex-wrap items-center gap-2">
                            <LemonButton
                                type="tertiary"
                                noPadding
                                className="max-w-full"
                                onClick={() => setDetailsExpanded(!detailsExpanded)}
                                aria-expanded={detailsExpanded}
                                aria-controls={detailsId}
                                data-attr="scout-rubric-title-details"
                            >
                                <span className="break-words text-left text-sm leading-5 font-semibold">{title}</span>
                            </LemonButton>
                            {!isSuggestion && !criterion.enabled && (
                                <LemonTag type="muted">Off for this scout</LemonTag>
                            )}
                        </div>
                        <p className="mt-1 mb-0 break-words text-sm leading-5 text-secondary">
                            {criterion.description}
                        </p>
                        {detailsExpanded && (
                            <dl
                                id={detailsId}
                                className="mt-3 mb-0 flex flex-col gap-3 rounded border bg-surface-secondary p-3"
                            >
                                <div className="flex flex-wrap gap-x-4 gap-y-1">
                                    <dt className="w-24 shrink-0 text-sm leading-5 font-semibold text-secondary">
                                        Passes when
                                    </dt>
                                    <dd className="m-0 min-w-0 flex-1 basis-60 break-words text-sm leading-5">
                                        {criterion.pass_condition}
                                    </dd>
                                </div>
                                <div className="flex flex-wrap gap-x-4 gap-y-1">
                                    <dt className="w-24 shrink-0 text-sm leading-5 font-semibold text-secondary">
                                        Applies to
                                    </dt>
                                    <dd className="m-0 min-w-0 flex-1 basis-60 break-words text-sm leading-5">
                                        {criterion.applicability}
                                    </dd>
                                </div>
                            </dl>
                        )}
                    </div>
                    <div className="-mt-1 flex flex-wrap items-center gap-0.5">
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={<IconPencil />}
                            onClick={() => {
                                onSelect?.(true)
                                onExpand()
                            }}
                            disabledReason={disabledReason}
                            aria-label={`Edit ${title}`}
                            tooltip="Edit criterion"
                            data-attr="scout-rubric-edit"
                        />
                        {!isSuggestion && criterion.source !== 'default' && (
                            <LemonButton
                                size="xsmall"
                                type="tertiary"
                                status="danger"
                                icon={<IconTrash />}
                                onClick={onRemove}
                                disabledReason={disabledReason}
                                aria-label={`Remove ${title}`}
                                tooltip="Remove criterion"
                                data-attr="scout-rubric-remove"
                            />
                        )}
                        <LemonButton
                            size="xsmall"
                            type="tertiary"
                            icon={
                                <IconChevronDown
                                    className={cn(
                                        'transition-transform motion-reduce:transition-none',
                                        detailsExpanded && 'rotate-180'
                                    )}
                                />
                            }
                            onClick={() => setDetailsExpanded(!detailsExpanded)}
                            aria-label={detailsLabel}
                            aria-expanded={detailsExpanded}
                            aria-controls={detailsId}
                            tooltip={detailsExpanded ? 'Hide details' : 'Show details'}
                            data-attr={isSuggestion ? 'scout-rubric-suggestion-details' : 'scout-rubric-details'}
                        />
                    </div>
                </>
            )}
        </div>
    )
}
