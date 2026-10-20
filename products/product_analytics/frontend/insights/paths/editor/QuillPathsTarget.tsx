import { useActions, useValues } from 'kea'

import { IconChevronDown, IconFunnels, IconX } from '@posthog/icons'
import { Button, ButtonGroup } from '@posthog/quill'

import { PathItemSelector } from 'lib/components/PropertyFilters/components/PathItemSelector'
import { QuillIconButton } from 'lib/components/QuillIconButton/QuillIconButton'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { FunnelsQuery, InsightVizNode, NodeKind, PathsQuery } from '~/queries/schema/schema-general'
import { FunnelPathType } from '~/types'

import { pathsDataLogic } from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'

import type { PathTargetProps } from './PathsTarget'

export function QuillPathsTarget({ position, insightProps }: PathTargetProps): JSX.Element {
    const { pathsFilter, funnelPathsFilter, taxonomicGroupTypes } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter, updateQuerySource } = useActions(pathsDataLogic(insightProps))

    const { startPoint, endPoint, pathGroupings } = pathsFilter || {}
    const { funnelPathType, funnelSource, funnelStep } = funnelPathsFilter || {}

    const overrideStartInput = funnelPathType && [FunnelPathType.between, FunnelPathType.after].includes(funnelPathType)
    const overrideEndInput = funnelPathType && [FunnelPathType.between, FunnelPathType.before].includes(funnelPathType)
    const overrideInputs = overrideStartInput || overrideEndInput

    const funnelSourceQuery: InsightVizNode | undefined = funnelSource
        ? { kind: NodeKind.InsightVizNode, source: funnelSource }
        : undefined
    const funnelSourceUrl = funnelSourceQuery ? urls.insightNew({ query: funnelSourceQuery }) : undefined

    const key = position === 'start' ? 'startPoint' : 'endPoint'
    const onChange = (item: string): void => {
        updateInsightFilter({ [key]: item })
    }
    const onReset = (): void => {
        updateQuerySource({
            pathsFilter: { ...pathsFilter, [key]: undefined },
            funnelPathsFilter: undefined,
        } as Partial<PathsQuery>)
    }

    function _getStepNameAtIndex(filters: FunnelsQuery, index: number): string {
        return filters.series[index - 1].name ?? ''
    }

    function _getStepLabel(funnelSource?: FunnelsQuery, index?: number, shift: number = 0): JSX.Element {
        if (funnelSource && index) {
            return (
                <div className="flex items-center gap-2">
                    <IconFunnels />
                    <span className="label">{`${
                        index > 0 ? 'Funnel step ' + (index + shift) : 'Funnel dropoff ' + index * -1
                    }: ${_getStepNameAtIndex(funnelSource, index > 0 ? index + shift : index * -1)}`}</span>
                </div>
            )
        }
        return <span />
    }

    function getStartPointLabel(): JSX.Element {
        if (funnelPathType) {
            if (funnelPathType === FunnelPathType.after) {
                return _getStepLabel(funnelSource, funnelStep)
            } else if (funnelPathType === FunnelPathType.between) {
                // funnel_step targets the later of the 2 events when specifying between so the start point index is shifted back 1
                return _getStepLabel(funnelSource, funnelStep, -1)
            }
            return <span />
        }
        return startPoint ? (
            <span className="label line-clamp-2 [overflow-wrap:anywhere]" title={startPoint}>
                {startPoint}
            </span>
        ) : (
            <span className="text-muted-foreground">Add start point</span>
        )
    }

    function getEndPointLabel(): JSX.Element {
        if (funnelPathType) {
            if (funnelPathType === FunnelPathType.before || funnelPathType === FunnelPathType.between) {
                return _getStepLabel(funnelSource, funnelStep)
            }
            return <span />
        }
        return endPoint ? (
            <span className="label line-clamp-2 [overflow-wrap:anywhere]" title={endPoint}>
                {endPoint}
            </span>
        ) : (
            <span className="text-muted-foreground">Add end point</span>
        )
    }

    const positionOptions = {
        start: {
            index: 0,
            getLabel: getStartPointLabel,
            pathItem: startPoint,
            closeButtonEnabled: startPoint || overrideStartInput,
            disabled: overrideEndInput && !overrideStartInput,
            funnelSourceLink: overrideStartInput ? funnelSourceUrl : undefined,
        },
        end: {
            index: 1,
            getLabel: getEndPointLabel,
            pathItem: endPoint,
            closeButtonEnabled: endPoint || overrideEndInput,
            disabled: overrideStartInput && !overrideEndInput,
            funnelSourceLink: overrideEndInput ? funnelSourceUrl : undefined,
        },
    }[position]

    return (
        <PathItemSelector
            pathItem={positionOptions.pathItem}
            index={positionOptions.index}
            onChange={onChange}
            taxonomicGroupTypes={taxonomicGroupTypes}
            disabled={overrideInputs}
            wildcardOptions={pathGroupings?.map((name) => ({ name }))}
        >
            <ButtonGroup className="w-full">
                <Button
                    variant="outline"
                    left
                    aria-pressed={overrideInputs || undefined}
                    data-attr={'new-prop-filter-' + positionOptions.index}
                    className="paths-endpoint-field min-w-0 flex-1"
                    disabled={positionOptions.disabled}
                    render={
                        positionOptions.funnelSourceLink ? (
                            <LinkPrimitive to={positionOptions.funnelSourceLink} />
                        ) : undefined
                    }
                >
                    <span className="min-w-0 flex-1 text-start">{positionOptions.getLabel()}</span>
                    {!positionOptions.closeButtonEnabled ? <IconChevronDown /> : null}
                </Button>
                {positionOptions.closeButtonEnabled ? (
                    <QuillIconButton
                        variant="outline"
                        label={position === 'start' ? 'Remove start point' : 'Remove end point'}
                        icon={<IconX />}
                        onClick={(e) => {
                            onReset()
                            e.stopPropagation()
                        }}
                    />
                ) : null}
            </ButtonGroup>
        </PathItemSelector>
    )
}
