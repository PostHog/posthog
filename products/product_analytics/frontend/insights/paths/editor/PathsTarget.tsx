import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'

import { PathItemSelector } from 'lib/components/PropertyFilters/components/PathItemSelector'
import { IconFunnelVertical } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { urls } from 'scenes/urls'

import { FunnelsQuery, InsightVizNode, NodeKind, PathsQuery } from '~/queries/schema/schema-general'
import { EditorFilterProps, FunnelPathType } from '~/types'

import { pathsDataLogic } from 'products/product_analytics/frontend/insights/paths/pathsDataLogic'

export function PathsTargetStart(props: EditorFilterProps): JSX.Element {
    return <PathsTarget position="start" {...props} />
}

export function PathsTargetEnd(props: EditorFilterProps): JSX.Element {
    return <PathsTarget position="end" {...props} />
}

type PathTargetProps = {
    position: 'start' | 'end'
} & EditorFilterProps

function PathsTarget({ position, insightProps }: PathTargetProps): JSX.Element {
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
                    <IconFunnelVertical className="text-2xl" />
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
            <span className="label text-secondary">Add start point</span>
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
            <span className="label text-secondary">Add end point</span>
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
            <LemonButton
                data-attr={'new-prop-filter-' + positionOptions.index}
                fullWidth
                className="paths-endpoint-field"
                type="secondary"
                active={overrideInputs}
                disabled={positionOptions.disabled}
                to={positionOptions.funnelSourceLink}
                sideAction={
                    positionOptions.closeButtonEnabled
                        ? {
                              icon: <IconX />,
                              type: 'tertiary',
                              onClick: (e) => {
                                  onReset()
                                  e.stopPropagation()
                              },
                          }
                        : null
                }
            >
                {positionOptions.getLabel()}
            </LemonButton>
        </PathItemSelector>
    )
}
