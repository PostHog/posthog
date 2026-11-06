import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { goalScoutFormLogic } from '../../../../logics/goal/goalScoutFormLogic'
import { FIELD_LABELS, type GoalFormField } from '../../../../utils/goal/form'

const FIELD_TARGETS: Record<GoalFormField, string> = {
    statement: '#goal-statement',
    title: '#goal-title',
    goal_insight: '#goal-insight, #goal-description',
    target: '#goal-target',
    guardrails: '[data-undecided] [data-guardrail-direction] button',
    budget: '#goal-budget',
    repository: '[data-attr="scout-repositories"] input',
}

export function GoalFormStatus(): JSX.Element {
    const { submitError, missing, submitDisabledReason, measureSearchLoading } = useValues(goalScoutFormLogic)
    const { reveal } = useActions(goalScoutFormLogic)
    const shown = measureSearchLoading ? missing.filter((part) => part.field !== 'goal_insight') : missing
    const focusField = (field: GoalFormField): void => {
        reveal(field)
        window.setTimeout(() => document.querySelector<HTMLElement>(FIELD_TARGETS[field])?.focus())
    }
    return (
        <div className="min-w-0 flex-1 basis-60 text-xs">
            {submitError ? (
                <p role="alert" className="m-0 text-danger">
                    {submitError.field ? (
                        <>
                            Check the{' '}
                            <Link onClick={() => submitError.field && focusField(submitError.field)}>
                                {FIELD_LABELS[submitError.field]}
                            </Link>{' '}
                            and try again.
                        </>
                    ) : (
                        submitError.message
                    )}
                </p>
            ) : shown.length > 0 ? (
                <p className="m-0 text-secondary">
                    Still needed:{' '}
                    {shown.map((part, index) => (
                        <span key={part.field}>
                            <Link subtle onClick={() => focusField(part.field)}>
                                {part.label}
                            </Link>
                            {index < shown.length - 1 ? ', ' : '.'}
                        </span>
                    ))}
                </p>
            ) : (
                submitDisabledReason &&
                !measureSearchLoading && <p className="m-0 text-secondary">{submitDisabledReason}</p>
            )}
        </div>
    )
}
