import { useActions, useValues } from 'kea'

import { LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { goalScoutFormLogic } from '../../../../logics/goal/goalScoutFormLogic'

export function GoalBeliefField({ large, onSubmit }: { large?: boolean; onSubmit?: () => void }): JSX.Element {
    const { goalForm, fieldErrors } = useValues(goalScoutFormLogic)
    const { setGoalFormValue, touchGoalFormField, measureFromBelief } = useActions(goalScoutFormLogic)
    return (
        <LemonField.Pure
            label={large ? undefined : 'What do you believe?'}
            htmlFor="goal-statement"
            error={fieldErrors.statement}
            help={
                large && !fieldErrors.statement
                    ? 'Next, the scout finds the measure in your data, suggests a target and guardrails, and names the goal.'
                    : undefined
            }
        >
            <LemonTextArea
                id="goal-statement"
                autoFocus={large}
                minRows={large ? 5 : 3}
                maxRows={10}
                value={goalForm.statement}
                onChange={(statement) => setGoalFormValue('statement', statement)}
                onBlur={() => {
                    touchGoalFormField('statement')
                    measureFromBelief()
                }}
                onPressCmdEnter={onSubmit}
                placeholder="Shoppers buy more when they see the total price early, because surprise costs at the end make them leave."
                className={large ? 'text-base' : undefined}
                data-attr="goal-scout-form-belief"
            />
        </LemonField.Pure>
    )
}
