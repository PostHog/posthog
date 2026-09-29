import { IconPencil, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard, LemonCheckbox, LemonInput, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ScoutRubricCriterionApi } from 'products/signals/frontend/generated/api.schemas'

export function ScoutRubricCriterionEditor({
    criterion,
    expanded,
    saving,
    onChange,
    onExpand,
    onRemove,
}: {
    criterion: ScoutRubricCriterionApi
    expanded: boolean
    saving: boolean
    onChange: (changes: Partial<ScoutRubricCriterionApi>) => void
    onExpand: () => void
    onRemove: () => void
}): JSX.Element {
    const disabledReason = saving ? 'Saving rubrics' : undefined
    return (
        <LemonCard hoverEffect={false} className="!p-3">
            <div className="flex flex-wrap items-center gap-2">
                <LemonCheckbox
                    checked={criterion.enabled}
                    onChange={(enabled) => onChange({ enabled })}
                    disabledReason={disabledReason}
                    label={criterion.title || 'New criterion'}
                    className="min-w-0 flex-1 break-words"
                    data-attr="scout-rubric-enable"
                />
                {criterion.source === 'default' && <LemonTag type="muted">Shared default</LemonTag>}
                <LemonButton
                    size="xsmall"
                    type="tertiary"
                    icon={<IconPencil />}
                    onClick={onExpand}
                    aria-label={`Edit ${criterion.title || 'new criterion'}`}
                    data-attr="scout-rubric-edit"
                >
                    {expanded ? 'Done editing' : 'Edit'}
                </LemonButton>
                {criterion.source !== 'default' && (
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        status="danger"
                        icon={<IconTrash />}
                        onClick={onRemove}
                        disabledReason={disabledReason}
                        aria-label={`Remove ${criterion.title || 'new criterion'}`}
                        data-attr="scout-rubric-remove"
                    />
                )}
            </div>
            {expanded ? (
                <div className="mt-3 flex flex-col gap-3">
                    <LemonField.Pure label="Name" htmlFor={`${criterion.id}-title`}>
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
                    <LemonField.Pure label="What to check" htmlFor={`${criterion.id}-description`}>
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
                    <LemonField.Pure label="What passing looks like" htmlFor={`${criterion.id}-pass`}>
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
                    <LemonField.Pure label="When this applies" htmlFor={`${criterion.id}-applicability`}>
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
                </div>
            ) : (
                <p className="mb-0 mt-2 break-words text-sm text-secondary">{criterion.description}</p>
            )}
        </LemonCard>
    )
}
