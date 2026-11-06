import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { GoalScoutDetailApi } from 'products/signals/frontend/generated/api.schemas'

import { goalScoutLogic } from '../../../../logics/goal/goalScoutLogic'
import { ideaReason } from '../../../../utils/goal/ideas'
import { type PlanField, stepValue } from '../../../../utils/goal/plan'

const FIELDS: { name: PlanField; label: string; unit: string; help: string; placeholder?: string }[] = [
    {
        name: 'audience',
        label: 'People a day',
        unit: 'people',
        help: 'People who reach the place this change touches.',
        placeholder: 'How many people a day',
    },
    { name: 'mde', label: 'Smallest change to find', unit: '%', help: 'A smaller change needs more days.' },
    { name: 'days', label: 'Days to run', unit: 'days', help: 'At least 2 days.' },
]

const MISSING_AUDIENCE = 'Not known yet. Count the people a day who reach the place this change touches.'

export function GoalBuildModal({ goal }: { goal: GoalScoutDetailApi }): JSX.Element {
    const { buildDialogIdea, buildDialogOpen, ideaPlans, busy, busyOperation, buildDisabledReason, ideaError } =
        useValues(goalScoutLogic({ id: goal.id }))
    const { openBuild, buildIdea, editPlan } = useActions(goalScoutLogic({ id: goal.id }))
    const item = goal.work.find((entry) => entry.id === buildDialogIdea)
    const plan = item ? ideaPlans[item.id] : undefined
    const building = !!item && busyOperation === `build:${item.id}`
    const reason = buildDisabledReason ?? plan?.disabledReason ?? (busy && !building ? 'Saving a change' : null)
    const anchor = goal.plan_anchor
    return (
        <LemonModal
            isOpen={buildDialogOpen && !!item}
            onClose={() => !building && openBuild(null)}
            title="Build and test this idea"
            description={item?.title}
            width={520}
            footer={
                <>
                    <LemonButton
                        type="secondary"
                        disabledReason={building ? 'Starting the build' : undefined}
                        onClick={() => openBuild(null)}
                        data-attr="goal-build-cancel"
                    >
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        loading={building}
                        disabledReason={reason ?? undefined}
                        onClick={() => item && buildIdea(item.id)}
                        data-attr="goal-build-confirm"
                    >
                        Build
                    </LemonButton>
                </>
            }
        >
            {item && (
                <div className="flex flex-col gap-4" data-attr="goal-build-dialog">
                    {item.assessment === 'not_supported' && (
                        <LemonBanner type="warning">
                            The scout has low confidence in this idea. {ideaReason(item)}
                        </LemonBanner>
                    )}
                    <p className="m-0 text-sm text-secondary">
                        {plan
                            ? 'The scout builds the change behind a feature flag and tests it with this plan.'
                            : 'The scout builds the change behind a feature flag. This metric does not have enough history to plan the test length yet, so the scout plans it when the test goes live.'}
                    </p>
                    {!plan && item.plan.audience ? (
                        <p className="m-0 text-xs text-tertiary tabular-nums">
                            About {humanFriendlyNumber(item.plan.audience)} people a day reach the place this change
                            touches.
                        </p>
                    ) : null}
                    {plan &&
                        FIELDS.map((field) => (
                            <LemonField.Pure
                                key={field.name}
                                label={field.label}
                                help={field.name === 'audience' && plan.audienceMissing ? MISSING_AUDIENCE : field.help}
                            >
                                <LemonInput
                                    value={plan.draft[field.name]}
                                    inputMode={field.name === 'mde' ? 'decimal' : 'numeric'}
                                    autoFocus={
                                        field.name === 'audience'
                                            ? plan.audienceMissing
                                            : field.name === 'days' && !!plan.disabledReason
                                    }
                                    suffix={<span className="text-secondary">{field.unit}</span>}
                                    placeholder={field.placeholder}
                                    disabled={building}
                                    onChange={(value) => editPlan(item.id, item.plan, anchor, field.name, value)}
                                    onKeyDown={(event) => {
                                        if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
                                            event.preventDefault()
                                            editPlan(
                                                item.id,
                                                item.plan,
                                                anchor,
                                                field.name,
                                                stepValue(
                                                    plan.draft[field.name],
                                                    field.name,
                                                    event.key === 'ArrowUp' ? 1 : -1
                                                )
                                            )
                                        }
                                    }}
                                    data-attr={`goal-plan-${field.name}`}
                                />
                            </LemonField.Pure>
                        ))}
                    {plan?.tooLong && (
                        <p className="m-0 flex items-start gap-1.5 text-xs text-secondary" aria-live="polite">
                            <IconInfo className="mt-0.5 size-3.5 shrink-0" />
                            This is longer than 4 weeks.
                        </p>
                    )}
                    {ideaError && (
                        <p role="alert" className="m-0 text-sm text-danger">
                            {ideaError}
                        </p>
                    )}
                </div>
            )}
        </LemonModal>
    )
}
