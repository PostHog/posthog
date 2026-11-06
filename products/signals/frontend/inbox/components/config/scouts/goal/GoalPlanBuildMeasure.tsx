import { useActions, useValues } from 'kea'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

import { goalScoutFormLogic } from '../../../../logics/goal/goalScoutFormLogic'

export function GoalPlanBuildMeasure(): JSX.Element {
    const { goalForm, describing, measureDraft, fieldErrors } = useValues(goalScoutFormLogic)
    const { setGoalFormValue, setDescribing, setPicking, touchGoalFormField } = useActions(goalScoutFormLogic)

    if (describing) {
        return (
            <div
                className="flex flex-col gap-2 rounded border border-primary bg-surface-primary px-4 py-3"
                data-attr="goal-plan-build-measure"
            >
                <div className="flex flex-wrap items-start gap-3">
                    <div className="flex min-w-0 flex-1 flex-col">
                        <span className="text-base font-semibold">An agent builds this measure</span>
                        <span className="text-xs text-secondary">
                            It adds tracking if an event is missing. This takes a few minutes after you create the
                            scout.
                        </span>
                    </div>
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={() => setDescribing(false)}
                        data-attr="goal-plan-build-measure-cancel"
                    >
                        Change
                    </LemonButton>
                </div>
                <LemonTextArea
                    id="goal-description"
                    minRows={2}
                    maxRows={4}
                    value={goalForm.goal_description}
                    onChange={(description) => setGoalFormValue('goal_description', description)}
                    onBlur={() => touchGoalFormField('goal_insight')}
                    placeholder="For example: share of new teams that invite a colleague in their first week"
                    data-attr="goal-plan-build-measure-description"
                />
                {fieldErrors.goal_insight && <span className="text-xs text-danger">{fieldErrors.goal_insight}</span>}
            </div>
        )
    }

    return (
        <div
            className="flex flex-col gap-3 rounded border border-primary bg-surface-primary px-4 py-3"
            data-attr="goal-plan-no-measure"
        >
            <div className="flex flex-col">
                <span className="text-base font-semibold">No measure in your data fits yet</span>
                <span className="text-xs text-secondary">
                    An agent can build it and add tracking if an event is missing.
                </span>
            </div>
            {measureDraft && <p className="m-0 rounded bg-surface-secondary px-3 py-2 text-sm">{measureDraft}</p>}
            <div className="flex flex-wrap items-center gap-2">
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => setDescribing(true)}
                    data-attr="goal-plan-build-measure-start"
                >
                    {measureDraft ? 'Build this measure' : 'Build a measure'}
                </LemonButton>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => setPicking(true)}
                    data-attr="goal-plan-pick-insight"
                >
                    Use an insight I have
                </LemonButton>
            </div>
        </div>
    )
}
