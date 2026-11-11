import './BreakdownTagMenu.scss'

import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonLabel, LemonSwitch } from '@posthog/lemon-ui'

import { QuillChartOptionNumberInput } from 'lib/components/ChartOptions/QuillChartOptionNumberInput'
import { QuillChartOptionSwitch } from 'lib/components/ChartOptions/QuillChartOptionSwitch'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { insightLogic } from 'scenes/insights/insightLogic'
import { insightVizDataLogic } from 'scenes/insights/insightVizDataLogic'

import { taxonomicBreakdownFilterLogic } from './taxonomicBreakdownFilterLogic'

const MIN_BREAKDOWN_LIMIT = 1
const MAX_BREAKDOWN_LIMIT = 1000

function clampBreakdownLimit(raw: string): number | null {
    const parsed = Number(raw)
    if (raw.trim() === '' || !Number.isFinite(parsed)) {
        return null
    }
    return Math.min(Math.max(parsed, MIN_BREAKDOWN_LIMIT), MAX_BREAKDOWN_LIMIT)
}

export const GlobalBreakdownOptionsMenu = (): JSX.Element | null => {
    const { insightProps } = useValues(insightLogic)
    const { isTrends } = useValues(insightVizDataLogic(insightProps))

    const { breakdownLimit, breakdownHideOtherAggregation, breakdownFilter } = useValues(taxonomicBreakdownFilterLogic)
    const { setBreakdownLimit, setBreakdownHideOtherAggregation } = useActions(taxonomicBreakdownFilterLogic)
    const quillSurface = useQuillSurface()
    const [limitDraft, setLimitDraft] = useState<string | null>(null)

    const commitBreakdownLimit = (raw: string): number | null => {
        const clamped = clampBreakdownLimit(raw)
        if (clamped !== null && clamped !== breakdownLimit) {
            setBreakdownLimit(clamped)
        }
        return clamped
    }

    // Cohort breakdowns are over an explicit, user-picked set — there's no long-tail to truncate
    // and nothing to bucket as "Other", so these controls don't apply.
    if (breakdownFilter?.breakdown_type === 'cohort') {
        return null
    }

    if (quillSurface) {
        return (
            <div className="flex flex-col gap-2">
                {isTrends && (
                    <QuillChartOptionSwitch
                        label='Group remaining values under "Other"'
                        info={`If you have over ${breakdownLimit} breakdown options, the smallest ones are aggregated under the label "Other". Use this toggle to show/hide the "Other" option.`}
                        checked={!breakdownHideOtherAggregation}
                        onChange={() => setBreakdownHideOtherAggregation(!breakdownHideOtherAggregation)}
                    />
                )}
                <QuillChartOptionNumberInput
                    label="Breakdown limit"
                    value={breakdownLimit}
                    onChange={(value) => value !== undefined && commitBreakdownLimit(String(value))}
                    draft={limitDraft ?? String(breakdownLimit)}
                    setDraft={setLimitDraft}
                    commit={() => {
                        if (limitDraft !== null) {
                            commitBreakdownLimit(limitDraft)
                            setLimitDraft(null)
                        }
                    }}
                />
            </div>
        )
    }

    return (
        <>
            {isTrends ? (
                <LemonSwitch
                    fullWidth
                    className="min-h-10 px-2"
                    checked={!breakdownHideOtherAggregation}
                    onChange={() => setBreakdownHideOtherAggregation(!breakdownHideOtherAggregation)}
                    label={
                        <div className="flex gap-1">
                            <span>Group remaining values under "Other"</span>
                            <Tooltip
                                title={
                                    <>
                                        If you have over {breakdownLimit} breakdown options, the smallest ones are
                                        aggregated under the label "Other". Use this toggle to show/hide the "Other"
                                        option.
                                    </>
                                }
                            >
                                <IconInfo className="text-secondary text-xl shrink-0" />
                            </Tooltip>
                        </div>
                    }
                />
            ) : null}
            <div className="px-2 flex gap-2 items-baseline">
                <LemonLabel className="font-medium" htmlFor="breakdown-limit">
                    Breakdown limit
                </LemonLabel>
                {/*
                 * Uncontrolled input so the user can freely clear the field while
                 * retyping. The DOM owns the draft; we only commit to the filter
                 * on blur / Enter. `key={breakdownLimit}` remounts the input when
                 * the committed value changes externally so `defaultValue` stays
                 * in sync.
                 */}
                <LemonInput
                    key={breakdownLimit}
                    id="breakdown-limit"
                    type="number"
                    min={MIN_BREAKDOWN_LIMIT}
                    max={MAX_BREAKDOWN_LIMIT}
                    defaultValue={breakdownLimit}
                    fullWidth={false}
                    className="w-20 ml-2"
                    onBlur={(event) => {
                        const target = event.currentTarget
                        target.value = String(commitBreakdownLimit(target.value) ?? breakdownLimit)
                    }}
                    onPressEnter={(event) => event.currentTarget.blur()}
                />
            </div>
        </>
    )
}
