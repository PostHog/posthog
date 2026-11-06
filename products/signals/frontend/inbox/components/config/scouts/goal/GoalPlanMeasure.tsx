import { useActions, useValues } from 'kea'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Spinner } from '@posthog/lemon-ui'

import { Sparkline } from 'lib/components/Sparkline'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { goalScoutFormLogic } from '../../../../logics/goal/goalScoutFormLogic'
import { measureValue, timeLabels } from '../../../../utils/goal/format'
import { formatMeasure } from '../../../../utils/goal/insightMetric'
import { GoalInsightPicker } from './GoalInsightPicker'
import { GoalPlanBuildMeasure } from './GoalPlanBuildMeasure'
import { GoalTargetField } from './GoalTargetField'
import { GoalTrendChart } from './GoalTrendChart'

const CARD = 'flex flex-col rounded border border-primary bg-surface-primary'

function MeasureLoading(): JSX.Element {
    return (
        <div className={`${CARD} gap-3 px-4 py-3`} aria-busy data-attr="goal-plan-measure-loading">
            <div className="flex items-center gap-2 text-sm text-secondary">
                <Spinner />
                Finding the measure in your data
            </div>
            <div className="flex flex-col gap-1.5">
                <LemonSkeleton className="h-5 w-64 max-w-full" />
                <LemonSkeleton className="h-3 w-40" />
            </div>
            <LemonSkeleton className="h-8 w-72 max-w-full" />
            <LemonSkeleton className="h-16 w-full" />
        </div>
    )
}

function MeasureChoice(): JSX.Element {
    const { measureOptions } = useValues(goalScoutFormLogic)
    const { selectPrimaryInsight, setDescribing, setPicking } = useActions(goalScoutFormLogic)
    return (
        <div className={CARD} data-attr="goal-plan-measure-choice">
            <div className="flex flex-col px-4 pt-3 pb-2">
                <span className="text-base font-semibold">Choose the measure</span>
                <span className="text-xs text-secondary">
                    {measureOptions.length === 1
                        ? 'One measure in your data fits your belief.'
                        : `${measureOptions.length} measures in your data fit your belief.`}
                </span>
            </div>
            <ul className="m-0 flex list-none flex-col p-0">
                {measureOptions.map((option) => {
                    const last = option.current ?? option.values.at(-1) ?? null
                    return (
                        <li key={option.insight} className="border-t border-primary">
                            <button
                                type="button"
                                className="flex w-full cursor-pointer items-center gap-4 border-0 bg-transparent px-4 py-2.5 text-left text-inherit hover:bg-fill-highlight-50"
                                onClick={() => selectPrimaryInsight(option.insight)}
                                data-attr="goal-scout-form-measure-option"
                            >
                                <span className="flex min-w-0 flex-1 flex-col">
                                    <span className="truncate text-sm font-semibold">{option.name}</span>
                                    <span className="line-clamp-2 text-xs text-secondary">
                                        {option.definition
                                            ? capitalizeFirstLetter(option.definition)
                                            : option.source === 'new'
                                              ? 'New measure'
                                              : 'Saved insight'}
                                    </span>
                                </span>
                                {option.values.length > 1 && (
                                    <Sparkline
                                        type="line"
                                        data={option.values}
                                        labels={option.dates}
                                        name={option.name}
                                        className="hidden h-6 w-20! shrink-0 @md:block"
                                    />
                                )}
                                <span className="w-14 shrink-0 text-right text-sm font-semibold tabular-nums">
                                    {last === null ? '' : measureValue(last, option.unit)}
                                </span>
                                <IconChevronRight className="size-4 shrink-0 text-tertiary" />
                            </button>
                        </li>
                    )
                })}
            </ul>
            <div className="flex flex-wrap items-center gap-2 border-t border-primary px-4 py-2.5">
                <span className="text-xs text-secondary">None of these?</span>
                <LemonButton
                    size="xsmall"
                    type="secondary"
                    onClick={() => setDescribing(true)}
                    data-attr="goal-plan-build-measure-start"
                >
                    Build a new measure
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

function InsightPick(): JSX.Element {
    const { goalForm, insightOptions, fieldErrors, measuredGoal } = useValues(goalScoutFormLogic)
    const { selectPrimaryInsight, setPicking, setDescribing, touchGoalFormField } = useActions(goalScoutFormLogic)
    return (
        <div className={`${CARD} gap-3 px-4 py-3`} data-attr="goal-plan-insight-pick">
            <div className="flex flex-wrap items-start gap-3">
                <div className="flex min-w-0 flex-1 flex-col">
                    <span className="text-base font-semibold">Use an insight you have</span>
                    <span className="text-xs text-secondary">A saved trends insight with one series.</span>
                </div>
                {measuredGoal && (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={() => setPicking(false)}
                        data-attr="goal-plan-insight-pick-back"
                    >
                        Back to suggestions
                    </LemonButton>
                )}
            </div>
            <GoalInsightPicker
                buttonId="goal-insight"
                value={goalForm.goal_insight}
                options={insightOptions}
                placeholder="Choose a saved insight"
                invalid={!!fieldErrors.goal_insight}
                onSelect={(insight) => {
                    selectPrimaryInsight(insight)
                    setPicking(false)
                }}
                onClose={() => touchGoalFormField('goal_insight')}
                onDescribe={() => {
                    setPicking(false)
                    setDescribing(true)
                }}
            />
            {fieldErrors.goal_insight && <span className="text-xs text-danger">{fieldErrors.goal_insight}</span>}
        </div>
    )
}

function SelectedMeasure(): JSX.Element {
    const { goalForm, measureOptions, insightNames, preview, previewLoading, display, locked } =
        useValues(goalScoutFormLogic)
    const { clearMeasure } = useActions(goalScoutFormLogic)
    const option = measureOptions.find((item) => item.insight === goalForm.goal_insight)
    const name = option?.name || insightNames[goalForm.goal_insight] || goalForm.goal_metric || 'Measure'
    const target = goalForm.target ? Number(goalForm.target) : null
    const values = preview?.values ?? option?.values ?? []
    const dates = preview?.dates ?? option?.dates ?? []
    return (
        <div className={CARD} data-attr="goal-plan-measure">
            <div className="flex items-start gap-3 px-4 pt-3">
                <div className="flex min-w-0 flex-1 flex-col">
                    <span className="flex min-w-0 items-center gap-2">
                        <span className="truncate text-base font-semibold">{name}</span>
                        {option?.source === 'new' && (
                            <LemonTag size="small" type="muted">
                                New
                            </LemonTag>
                        )}
                    </span>
                    {option?.definition && (
                        <span className="line-clamp-2 text-xs text-secondary">
                            {capitalizeFirstLetter(option.definition)}
                        </span>
                    )}
                </div>
                {!locked && (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        onClick={clearMeasure}
                        data-attr="goal-plan-measure-change"
                    >
                        Change
                    </LemonButton>
                )}
            </div>
            <div className="flex flex-col gap-4 px-4 pt-3">
                <GoalTargetField />
            </div>
            <div className="px-4 pt-2 pb-3">
                {previewLoading && !values.length ? (
                    <LemonSkeleton className="h-16 w-full" />
                ) : values.length < 2 ? (
                    <div className="flex h-16 items-center justify-center rounded border border-dashed border-primary px-2 text-center text-xs text-secondary">
                        No data for this measure yet. The scout starts measuring when you create it.
                    </div>
                ) : (
                    <GoalTrendChart
                        values={values}
                        labels={timeLabels(dates)}
                        reference={target !== null && Number.isFinite(target) ? target : null}
                        referenceLabel="Target"
                        format={(value) => formatMeasure(value, display)}
                    />
                )}
                {option?.test_days ? (
                    <p className="m-0 mt-1 text-xs text-tertiary">
                        One test takes about {option.test_days} {option.test_days === 1 ? 'day' : 'days'} at this
                        traffic.
                    </p>
                ) : null}
            </div>
        </div>
    )
}

export function GoalPlanMeasure(): JSX.Element {
    const { goalForm, describing, measureOptions, measureSearchLoading, picking, measuredGoal } =
        useValues(goalScoutFormLogic)
    const insight = goalForm.goal_insight
    if (!insight && measureSearchLoading) {
        return <MeasureLoading />
    }
    if (describing || (!insight && !picking && !!measuredGoal && !measureOptions.length)) {
        return <GoalPlanBuildMeasure />
    }
    if (!insight && measureOptions.length && !picking) {
        return <MeasureChoice />
    }
    if (!insight) {
        return <InsightPick />
    }
    return <SelectedMeasure />
}
