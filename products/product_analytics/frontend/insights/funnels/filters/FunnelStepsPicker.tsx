import { useActions, useValues } from 'kea'

import { LemonSelect } from '@posthog/lemon-ui'

import { EntityFilterInfo } from 'lib/components/EntityFilterInfo'
import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { insightLogic } from 'scenes/insights/insightLogic'

import { QuillToolbarSelect } from 'products/product_analytics/frontend/insights/shared/QuillToolbarSelect'

import { funnelDataLogic } from '../funnelDataLogic'

interface StepOption {
    value: number
    label: string
    labelInMenu: JSX.Element
}

export function FunnelStepsPicker(): JSX.Element | null {
    const { insightProps, editingDisabledReason } = useValues(insightLogic)
    const { series, isFunnelWithEnoughSteps, funnelsFilter } = useValues(funnelDataLogic(insightProps))
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    const onChange = (funnelFromStep?: number, funnelToStep?: number): void => {
        updateInsightFilter({ funnelFromStep, funnelToStep })
    }

    const filterSteps = series || []
    const numberOfSeries = series?.length || 0
    const allSteps = Array.from(Array(numberOfSeries).keys())
    const defaultToStep = Math.max(numberOfSeries - 1, 1)
    const maxFromStep = Math.max(Math.min(funnelsFilter?.funnelToStep ?? defaultToStep, numberOfSeries - 1), 1)
    const fromRange = isFunnelWithEnoughSteps ? allSteps.slice(0, maxFromStep) : [0]
    const toRange = isFunnelWithEnoughSteps ? allSteps.slice((funnelsFilter?.funnelFromStep ?? 0) + 1) : [1]

    const optionsForRange = (range: number[]): StepOption[] => {
        return range
            .map((stepIndex): StepOption | null => {
                return filterSteps[stepIndex]
                    ? {
                          value: stepIndex,
                          label: `Step ${stepIndex + 1}`,
                          labelInMenu: (
                              <>
                                  <span>Step {stepIndex + 1} – </span>
                                  <EntityFilterInfo filter={filterSteps[stepIndex]} />
                              </>
                          ),
                      }
                    : null
            })
            .filter((option): option is StepOption => option !== null)
    }

    const selectedFromStep = funnelsFilter?.funnelFromStep || 0
    const selectedToStep = funnelsFilter?.funnelToStep || Math.max(numberOfSeries - 1, 1)

    if (quillSurface) {
        return (
            <div className="flex items-center gap-1">
                <span className="text-muted-foreground">&nbsp;from</span>
                <QuillToolbarSelect
                    size="sm"
                    value={selectedFromStep}
                    options={optionsForRange(fromRange)}
                    onChange={(step) => onChange(step, funnelsFilter?.funnelToStep)}
                    disabled={!isFunnelWithEnoughSteps}
                    disabledReason={editingDisabledReason}
                />
                <span className="text-muted-foreground">to</span>
                <QuillToolbarSelect
                    size="sm"
                    value={selectedToStep}
                    options={optionsForRange(toRange)}
                    onChange={(step) => onChange(funnelsFilter?.funnelFromStep, step)}
                    disabled={!isFunnelWithEnoughSteps}
                    disabledReason={editingDisabledReason}
                />
            </div>
        )
    }

    return (
        <div className="flex items-center">
            <span className="text-secondary">&nbsp;from</span>
            <LemonSelect
                size="small"
                className="mx-1"
                dropdownMatchSelectWidth={false}
                optionTooltipPlacement="bottom-start"
                disabled={!isFunnelWithEnoughSteps}
                options={optionsForRange(fromRange)}
                value={selectedFromStep}
                onChange={(fromStep: number | null) =>
                    fromStep != null && onChange(fromStep, funnelsFilter?.funnelToStep)
                }
                disabledReason={editingDisabledReason}
            />
            <span className="text-secondary">to</span>
            <LemonSelect
                size="small"
                className="mx-1"
                dropdownMatchSelectWidth={false}
                optionTooltipPlacement="bottom-start"
                disabled={!isFunnelWithEnoughSteps}
                options={optionsForRange(toRange)}
                value={selectedToStep}
                onChange={(toStep: number | null) => toStep != null && onChange(funnelsFilter?.funnelFromStep, toStep)}
                disabledReason={editingDisabledReason}
            />
        </div>
    )
}
