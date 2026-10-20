import { useActions, useValues } from 'kea'

import { IconFilter, IconTrash } from '@posthog/icons'

import { QuillIconButton } from 'lib/components/QuillIconButton/QuillIconButton'
import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { AnyEntityNode, FunnelsDataWarehouseNode, NodeKind } from '~/queries/schema/schema-general'

import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'
import { getClampedFunnelStepRange } from 'products/product_analytics/frontend/insights/funnels/funnelUtils'

import type { ExclusionRowSuffixProps } from './ExclusionRowSuffix'

export function QuillExclusionRowSuffix({ index, onClose, typeKey }: ExclusionRowSuffixProps): JSX.Element {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter, series, isFunnelWithEnoughSteps, exclusionDefaultStepRange } = useValues(
        funnelDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))

    const mountedLogic = entityFilterLogic.findMounted({ typeKey })
    const propertyFiltersVisible = (mountedLogic && mountedLogic.values.entityFilterVisible[index]) || false

    const exclusions = funnelsFilter?.exclusions
    const numberOfSeries = series?.length || 0

    const stepRange = {
        funnelFromStep: exclusions?.[index]?.funnelFromStep ?? exclusionDefaultStepRange.funnelFromStep,
        funnelToStep: exclusions?.[index]?.funnelToStep ?? exclusionDefaultStepRange.funnelToStep,
    }

    const onChange = (funnelFromStep = stepRange.funnelFromStep, funnelToStep = stepRange.funnelToStep): void => {
        // Funnels don't support group nodes
        const nonGroupSeries: AnyEntityNode<FunnelsDataWarehouseNode>[] | null | undefined = series?.filter(
            (s): s is AnyEntityNode<FunnelsDataWarehouseNode> => s.kind !== NodeKind.GroupNode
        )
        const newStepRange = getClampedFunnelStepRange({ funnelFromStep, funnelToStep }, nonGroupSeries)
        const newExclusions = funnelsFilter?.exclusions?.map((exclusion, exclusionIndex) =>
            exclusionIndex === index ? { ...exclusion, ...newStepRange } : exclusion
        )
        updateInsightFilter({ exclusions: newExclusions })
    }

    const stepOption = (stepIndex: number): { value: number; label: string } => ({
        value: stepIndex,
        label: `Step ${stepIndex + 1}`,
    })
    const disabledReason = !isFunnelWithEnoughSteps ? 'Add at least two steps to the funnel first' : undefined

    return (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 w-full p-1 my-1">
            <div className="flex flex-shrink-0 items-center gap-2">
                <span>between</span>
                <QuillSelect
                    value={stepRange.funnelFromStep || 0}
                    onChange={(fromStep) => onChange(fromStep)}
                    options={Array.from(Array(numberOfSeries).keys()).slice(0, -1).map(stepOption)}
                    disabledReason={disabledReason}
                />
            </div>
            <div className="flex flex-shrink-0 items-center gap-2">
                <span>and</span>
                <QuillSelect
                    value={stepRange.funnelToStep || (stepRange.funnelFromStep ?? 0) + 1}
                    onChange={(toStep) => onChange(stepRange.funnelFromStep, toStep)}
                    options={Array.from(Array(numberOfSeries).keys())
                        .slice((stepRange.funnelFromStep ?? 0) + 1)
                        .map(stepOption)}
                    disabledReason={disabledReason}
                />
            </div>
            <div className="flex items-center gap-1 ml-auto">
                <QuillIconButton
                    label="Show filters"
                    icon={<IconFilter />}
                    count={exclusions?.[index]?.properties?.length || 0}
                    aria-pressed={propertyFiltersVisible}
                    data-attr={`show-prop-filter-${index}`}
                    onClick={() => mountedLogic?.actions.setEntityFilterVisibility(index, !propertyFiltersVisible)}
                />
                <QuillIconButton
                    label="Delete event exclusion series"
                    icon={<IconTrash />}
                    onClick={onClose}
                    data-attr="delete-prop-exclusion-filter"
                />
            </div>
        </div>
    )
}
