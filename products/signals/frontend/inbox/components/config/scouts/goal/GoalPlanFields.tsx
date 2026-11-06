import { useActions, useValues } from 'kea'

import { LemonInput, LemonInputSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { goalScoutFormLogic } from '../../../../logics/goal/goalScoutFormLogic'
import { LOCKED_REASON } from '../../../../utils/goal/form'
import { ScoutRepositoriesPicker } from '../ScoutRepositoriesPicker'
import { GoalGuardrailsField } from './GoalGuardrailsField'
import { GoalPlanMeasure } from './GoalPlanMeasure'

export function GoalPlanFields(): JSX.Element {
    const {
        goalForm,
        title,
        titleEdited,
        isNew,
        fieldErrors,
        areas,
        beliefLabelsLoading,
        repositories,
        repositorySource,
        locked,
    } = useValues(goalScoutFormLogic)
    const { setGoalFormValue, touchGoalFormField } = useActions(goalScoutFormLogic)
    const suggesting = isNew && beliefLabelsLoading
    const repositoryHelp = locked
        ? LOCKED_REASON
        : repositorySource === 'last'
          ? null
          : repositorySource === 'only'
            ? 'The only repository connected to this project.'
            : repositories.length > 1
              ? 'The scout reads all of them. Pull requests go where the change belongs.'
              : 'The scout opens pull requests here when you choose an idea.'

    return (
        <>
            <div className="flex flex-col gap-4">
                <GoalPlanMeasure />
                <GoalGuardrailsField />
            </div>

            <div className="grid grid-cols-1 gap-x-4 gap-y-3 border-t border-primary pt-4 @lg:grid-cols-2">
                <LemonField.Pure className="min-w-0" label="Name" htmlFor="goal-title" error={fieldErrors.title}>
                    <LemonInput
                        id="goal-title"
                        maxLength={160}
                        value={suggesting && !titleEdited ? '' : title}
                        status={fieldErrors.title ? 'danger' : 'default'}
                        onChange={(value) => setGoalFormValue('title', value)}
                        onBlur={() => touchGoalFormField('title')}
                        placeholder={suggesting ? 'Suggesting a name…' : 'Show the total price early'}
                        data-attr="goal-scout-form-name"
                    />
                </LemonField.Pure>
                <LemonField.Pure className="min-w-0" label="Product area" showOptional>
                    <LemonInputSelect
                        mode="single"
                        allowCustomValues
                        options={[...new Set([...areas, ...(goalForm.area ? [goalForm.area] : [])])].map((area) => ({
                            key: area,
                            label: area,
                        }))}
                        value={goalForm.area ? [goalForm.area] : []}
                        onChange={(values) => setGoalFormValue('area', (values[0] ?? '').slice(0, 120))}
                        placeholder={suggesting ? 'Suggesting an area…' : 'For example, Checkout'}
                        fullWidth
                        data-attr="goal-scout-form-area"
                    />
                </LemonField.Pure>
                <LemonField.Pure
                    className="min-w-0"
                    label="Budget"
                    htmlFor="goal-budget"
                    error={fieldErrors.budget}
                    help={fieldErrors.budget ? undefined : 'The scout stops when it has spent this much.'}
                >
                    <LemonInput
                        id="goal-budget"
                        inputMode="decimal"
                        autoComplete="off"
                        value={goalForm.budget}
                        status={fieldErrors.budget ? 'danger' : 'default'}
                        onChange={(value) => setGoalFormValue('budget', value.replace(',', '.'))}
                        onBlur={() => touchGoalFormField('budget')}
                        placeholder="20"
                        prefix={<span className="text-secondary">$</span>}
                        suffix={<span className="text-secondary">USD</span>}
                        data-attr="goal-scout-form-budget"
                    />
                </LemonField.Pure>
            </div>
            <div className="flex flex-col gap-1">
                <ScoutRepositoriesPicker
                    selectedRepositories={repositories}
                    onChange={(value) => {
                        setGoalFormValue('repositories', value)
                        touchGoalFormField('repository')
                    }}
                    disabledReason={locked ? LOCKED_REASON : undefined}
                />
                {fieldErrors.repository ? (
                    <span className="text-xs text-danger">{fieldErrors.repository}</span>
                ) : (
                    repositoryHelp && <span className="text-xs text-secondary">{repositoryHelp}</span>
                )}
            </div>
        </>
    )
}
