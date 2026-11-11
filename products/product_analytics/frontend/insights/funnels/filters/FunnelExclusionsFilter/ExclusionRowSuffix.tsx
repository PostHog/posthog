import { useActions, useValues } from 'kea'

import { IconFilter, IconTrash } from '@posthog/icons'
import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { entityFilterLogic } from 'scenes/insights/filters/ActionFilter/entityFilterLogic'
import { insightLogic } from 'scenes/insights/insightLogic'

import { AnyEntityNode, FunnelsDataWarehouseNode, NodeKind } from '~/queries/schema/schema-general'

import { funnelDataLogic } from 'products/product_analytics/frontend/insights/funnels/funnelDataLogic'
import { getClampedFunnelStepRange } from 'products/product_analytics/frontend/insights/funnels/funnelUtils'

import { QuillExclusionRowSuffix } from './QuillExclusionRowSuffix'

type ExclusionRowSuffixComponentBaseProps = {
    index: number
    onClose?: () => void
    typeKey: string
}

export function ExclusionRowSuffix({
    index,
    onClose,
    typeKey,
}: ExclusionRowSuffixComponentBaseProps): JSX.Element | null {
    const { insightProps } = useValues(insightLogic)
    const { funnelsFilter, series, isFunnelWithEnoughSteps, exclusionDefaultStepRange } = useValues(
        funnelDataLogic(insightProps)
    )
    const { updateInsightFilter } = useActions(funnelDataLogic(insightProps))
    const quillSurface = useQuillSurface()

    // Get the entity filter logic that was created by the parent ActionFilter component
    const mountedLogic = entityFilterLogic.findMounted({ typeKey })

    // Use the logic for visibility state if it exists, otherwise use local state
    const propertyFiltersVisible = (mountedLogic && mountedLogic.values.entityFilterVisible[index]) || false

    const exclusions = funnelsFilter?.exclusions
    const numberOfSeries = series?.length || 0

    const stepRange = {
        funnelFromStep: exclusions?.[index]?.funnelFromStep ?? exclusionDefaultStepRange.funnelFromStep,
        funnelToStep: exclusions?.[index]?.funnelToStep ?? exclusionDefaultStepRange.funnelToStep,
    }

    const onChange = (funnelFromStep = stepRange.funnelFromStep, funnelToStep = stepRange.funnelToStep): void => {
        // Filter out GroupNodes as funnels don't support them
        const nonGroupSeries: AnyEntityNode<FunnelsDataWarehouseNode>[] | null | undefined = series?.filter(
            (s): s is AnyEntityNode<FunnelsDataWarehouseNode> => s.kind !== NodeKind.GroupNode
        )
        const newStepRange = getClampedFunnelStepRange({ funnelFromStep, funnelToStep }, nonGroupSeries)
        const newExclusions = funnelsFilter?.exclusions?.map((exclusion, exclusionIndex) =>
            exclusionIndex === index ? { ...exclusion, ...newStepRange } : exclusion
        )
        updateInsightFilter({ exclusions: newExclusions })
    }

    const togglePropertyFiltersVisibility = (): void => {
        if (mountedLogic) {
            mountedLogic.actions.setEntityFilterVisibility(index, !propertyFiltersVisible)
        }
    }

    const stepOptions = Array.from(Array(numberOfSeries).keys()).map((stepIndex) => ({
        value: stepIndex,
        label: `Step ${stepIndex + 1}`,
    }))
    const fromOptions = stepOptions.slice(0, -1)
    const toOptions = stepOptions.slice((stepRange.funnelFromStep ?? 0) + 1)
    const fromStep = stepRange.funnelFromStep || 0
    const toStep = stepRange.funnelToStep || (stepRange.funnelFromStep ?? 0) + 1
    const propertyFilterCount = exclusions?.[index]?.properties?.length || 0

    if (quillSurface) {
        return (
            <QuillExclusionRowSuffix
                index={index}
                fromStep={fromStep}
                toStep={toStep}
                fromOptions={fromOptions}
                toOptions={toOptions}
                onFromChange={(funnelFromStep) => onChange(funnelFromStep)}
                onToChange={(nextToStep) => onChange(stepRange.funnelFromStep, nextToStep)}
                disabledReason={isFunnelWithEnoughSteps ? undefined : 'Funnels require at least two steps.'}
                propertyFilterCount={propertyFilterCount}
                onToggleFilters={togglePropertyFiltersVisibility}
                onClose={onClose}
            />
        )
    }

    const propertyFiltersButton = (
        <IconWithCount key="property-filter" count={propertyFilterCount} showZero={false}>
            <LemonButton
                icon={<IconFilter />}
                title="Show filters"
                data-attr={`show-prop-filter-${index}`}
                noPadding
                onClick={togglePropertyFiltersVisibility}
            />
        </IconWithCount>
    )

    return (
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 w-full p-1 my-1">
            <div className="flex flex-shrink-0 items-center gap-2">
                <span>between</span>
                <LemonSelect
                    className="flex-shrink-0"
                    size="small"
                    value={fromStep}
                    onChange={onChange}
                    options={fromOptions}
                    disabled={!isFunnelWithEnoughSteps}
                />
            </div>
            <div className="flex flex-shrink-0 items-center gap-2">
                <span>and</span>
                <LemonSelect
                    className="flex-shrink-0"
                    size="small"
                    value={toStep}
                    onChange={(nextToStep: number) => onChange(stepRange.funnelFromStep, nextToStep)}
                    options={toOptions}
                    disabled={!isFunnelWithEnoughSteps}
                />
            </div>
            <div className="flex items-center gap-1 ml-auto">
                {propertyFiltersButton}
                <LemonButton
                    size="small"
                    icon={<IconTrash />}
                    onClick={onClose}
                    data-attr="delete-prop-exclusion-filter"
                    title="Delete event exclusion series"
                    noPadding
                />
            </div>
        </div>
    )
}
