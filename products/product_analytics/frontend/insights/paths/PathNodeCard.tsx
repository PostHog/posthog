import { useActions, useValues } from 'kea'
import { CSSProperties, useState } from 'react'

import { Popover } from 'lib/lemon-ui/Popover'

import { FunnelPathsFilter } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { PATH_NODE_CARD_LEFT_OFFSET, PATH_NODE_CARD_WIDTH } from './constants'
import { PathNodeCardButton } from './PathNodeCardButton'
import { PathNodeCardMenu } from './PathNodeCardMenu'
import { pathsDataLogic } from './pathsDataLogic'
import { PathNodeData, calculatePathNodeCardTop, isSelectedPathStartOrEnd, pageUrl } from './pathUtils'

export type PathNodeCardProps = {
    insightProps: InsightLogicProps
    node: PathNodeData
    canvasHeight: number
    onMouseEnter?: () => void
    onMouseLeave?: () => void
}

function getCardStyle(
    node: PathNodeData,
    isPathEnd: boolean,
    isSelected: boolean,
    canvasHeight: number
): CSSProperties {
    return {
        width: PATH_NODE_CARD_WIDTH,
        left: !isPathEnd
            ? node.x0 + PATH_NODE_CARD_LEFT_OFFSET
            : node.x0 + PATH_NODE_CARD_LEFT_OFFSET - PATH_NODE_CARD_WIDTH,
        top: node.resolvedTop ?? calculatePathNodeCardTop(node, canvasHeight),
        border: `1px solid ${isSelected ? 'purple' : node.active ? 'var(--paths-link-hover)' : 'var(--color-border-primary)'}`,
        zIndex: node.active ? 10 : 'auto',
        boxShadow: node.active ? '0 2px 10px rgba(0, 0, 0, 0.18), 0 0 0 1px var(--paths-link-hover)' : 'none',
        opacity: node.active ? 1 : undefined,
    }
}

export function PathNodeCard({
    insightProps,
    node,
    canvasHeight,
    onMouseEnter,
    onMouseLeave,
}: PathNodeCardProps): JSX.Element | null {
    const [popoverVisible, setPopoverVisible] = useState(false)
    const { pathsFilter: _pathsFilter, funnelPathsFilter: _funnelPathsFilter } = useValues(pathsDataLogic(insightProps))
    const { updateInsightFilter, openPersonsModal, viewPathToFunnel } = useActions(pathsDataLogic(insightProps))

    const pathsFilter = _pathsFilter || {}
    const funnelPathsFilter = _funnelPathsFilter || ({} as FunnelPathsFilter)

    if (!node.visible) {
        return null
    }

    // Attention: targetLinks are the incoming links, sourceLinks are the outgoing links
    const isPathStart = node.targetLinks.length === 0
    const isPathEnd = node.sourceLinks.length === 0
    const continuingCount = node.sourceLinks.reduce((prev, curr) => prev + curr.value, 0)
    const dropOffCount = node.value - continuingCount
    const averageConversionTime = !isPathStart
        ? node.targetLinks.reduce((prev, curr) => prev + curr.average_conversion_time / 1000, 0) /
          node.targetLinks.length
        : null

    const handleMouseEnter = (): void => {
        setPopoverVisible(true)
        onMouseEnter?.()
    }

    const handleMouseLeave = (): void => {
        setPopoverVisible(false)
        onMouseLeave?.()
    }

    return (
        <Popover
            visible={popoverVisible}
            overlay={
                <PathNodeCardMenu
                    name={node.name}
                    count={node.value}
                    continuingCount={continuingCount}
                    dropOffCount={dropOffCount}
                    averageConversionTime={averageConversionTime}
                    isPathStart={isPathStart}
                    isPathEnd={isPathEnd}
                    openPersonsModal={openPersonsModal}
                />
            }
            placement="bottom"
            padded={false}
            matchWidth
            onMouseLeaveInside={handleMouseLeave}
        >
            <div
                className={`PathNodeCard absolute rounded bg-surface-primary p-1${node.active ? ' PathNodeCard--active' : ''}`}
                // eslint-disable-next-line react/forbid-dom-props
                style={getCardStyle(
                    node,
                    isPathEnd,
                    isSelectedPathStartOrEnd(pathsFilter, funnelPathsFilter, node),
                    canvasHeight
                )}
                data-attr="path-node-card-button"
                onMouseEnter={handleMouseEnter}
                onMouseLeave={handleMouseLeave}
            >
                <PathNodeCardButton
                    name={node.name}
                    count={node.value}
                    node={node}
                    viewPathToFunnel={viewPathToFunnel}
                    openPersonsModal={openPersonsModal}
                    setFilter={updateInsightFilter}
                    filter={pathsFilter}
                    showFullUrls={!!pathsFilter.showFullUrls}
                    tooltipContent={pageUrl(node, true, true)}
                />
            </div>
        </Popover>
    )
}
