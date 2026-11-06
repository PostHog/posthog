import { useActions, useValues } from 'kea'

import { IconPlus, IconX } from '@posthog/icons'
import { LemonButton, LemonInput, LemonSegmentedButton, Spinner } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { goalScoutFormLogic } from '../../../../logics/goal/goalScoutFormLogic'
import { LOCKED_REASON, MAX_GUARDRAILS } from '../../../../utils/goal/form'
import { GoalInsightPicker } from './GoalInsightPicker'

const DIRECTIONS: { value: 'increase' | 'decrease'; label: string }[] = [
    { value: 'increase', label: 'Higher is better' },
    { value: 'decrease', label: 'Lower is better' },
]

export function GoalGuardrailsField(): JSX.Element {
    const {
        goalForm,
        guardrailOptions,
        insightNames,
        fieldErrors,
        guardrailChips,
        guardrailSuggestionsLoading,
        locked,
    } = useValues(goalScoutFormLogic)
    const { addGuardrail, changeGuardrail, removeGuardrail, adoptGuardrail } = useActions(goalScoutFormLogic)
    const guardrails = goalForm.secondary_metrics
    const canAdd = !locked && guardrails.length < MAX_GUARDRAILS
    const disabledReason = locked ? LOCKED_REASON : undefined

    return (
        <LemonField.Pure
            label="Guardrails"
            showOptional
            error={fieldErrors.guardrails}
            help={
                fieldErrors.guardrails
                    ? undefined
                    : locked
                      ? LOCKED_REASON
                      : 'Metrics that must not get worse while the scout tests ideas.'
            }
        >
            <div className="flex flex-col gap-2">
                {guardrails.length > 0 && (
                    <ul className="m-0 flex list-none flex-col gap-1 p-0">
                        {guardrails.map((metric) => {
                            const name = insightNames[metric.insight] || metric.name || metric.insight
                            return (
                                <li
                                    key={metric.insight}
                                    className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded border border-primary py-1 ps-3 pe-1"
                                    data-guardrail={metric.insight}
                                    data-undecided={metric.direction ? undefined : ''}
                                >
                                    <span className="min-w-0 flex-1 basis-32 truncate text-sm font-medium" title={name}>
                                        {name}
                                    </span>
                                    <div data-guardrail-direction>
                                        <LemonSegmentedButton
                                            size="xsmall"
                                            value={metric.direction ?? undefined}
                                            onChange={(direction) => changeGuardrail(metric.insight, { direction })}
                                            options={DIRECTIONS.map((option) => ({ ...option, disabledReason }))}
                                        />
                                    </div>
                                    {metric.direction ? (
                                        <span className="flex items-center gap-1.5 text-xs text-secondary">
                                            May get worse by
                                            <LemonInput
                                                size="xsmall"
                                                className="w-16"
                                                inputMode="decimal"
                                                disabled={locked}
                                                value={String(Math.round((metric.max_regression ?? 0.05) * 1000) / 10)}
                                                aria-label={`${name}: largest drop to allow, in percent`}
                                                onChange={(value) => {
                                                    const next = Number(value)
                                                    if (Number.isFinite(next)) {
                                                        changeGuardrail(metric.insight, {
                                                            max_regression: Math.min(100, Math.max(0, next)) / 100,
                                                        })
                                                    }
                                                }}
                                                suffix={<span className="text-secondary">%</span>}
                                            />
                                        </span>
                                    ) : (
                                        <span className="text-xs text-secondary">Choose which way is better</span>
                                    )}
                                    {!locked && (
                                        <LemonButton
                                            size="xsmall"
                                            icon={<IconX />}
                                            tooltip="Remove guardrail"
                                            aria-label={`Remove ${name}`}
                                            onClick={() => removeGuardrail(metric.insight)}
                                            data-attr="goal-scout-form-remove-guardrail"
                                        />
                                    )}
                                </li>
                            )
                        })}
                    </ul>
                )}
                {canAdd && (
                    <div className="flex flex-wrap items-center gap-1" aria-busy={guardrailSuggestionsLoading}>
                        {guardrailChips.map((option) => (
                            <LemonButton
                                key={option.insight}
                                type="secondary"
                                size="xsmall"
                                icon={<IconPlus />}
                                tooltip={option.definition}
                                onClick={() => adoptGuardrail(option)}
                                data-attr="goal-scout-form-guardrail-chip"
                            >
                                {option.name}
                            </LemonButton>
                        ))}
                        <GoalInsightPicker
                            compact
                            value=""
                            options={guardrailOptions}
                            placeholder={guardrailChips.length ? 'Other' : 'Add a guardrail'}
                            onSelect={(insight) => {
                                addGuardrail(insight)
                                window.setTimeout(() =>
                                    document
                                        .querySelector<HTMLElement>(
                                            `[data-guardrail="${insight}"] [data-guardrail-direction] button`
                                        )
                                        ?.focus()
                                )
                            }}
                        />
                        {guardrailSuggestionsLoading && (
                            <span className="ml-1 flex items-center gap-1 text-xs text-secondary">
                                <Spinner /> Finding guardrails…
                            </span>
                        )}
                    </div>
                )}
            </div>
        </LemonField.Pure>
    )
}
