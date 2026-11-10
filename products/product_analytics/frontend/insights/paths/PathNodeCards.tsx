import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { useChartLayout, useSankeyLayout } from '@posthog/quill-charts'

import { PathsLink } from '~/queries/schema/schema-general'
import { InsightLogicProps } from '~/types'

import { PathNodeCard } from './PathNodeCard'
import { toPathNodeData } from './pathsChartData'
import { pathsInteractionLogic } from './pathsInteractionLogic'

export interface PathNodeCardsProps {
    insightProps: InsightLogicProps
}

/** Chart overlay: hands the laid-out nodes to the interaction logic and renders one card per
 *  node the logic decides to show. */
export function PathNodeCards({ insightProps }: PathNodeCardsProps): JSX.Element {
    const { layout } = useSankeyLayout<unknown, PathsLink>()
    const { dimensions } = useChartLayout()
    const interactionLogic = pathsInteractionLogic(insightProps)
    const { resolvedNodeCards, cardPopoverIndex } = useValues(interactionLogic)
    const { setNodes, hoverCard, unhoverCard } = useActions(interactionLogic)

    const nodes = useMemo(() => toPathNodeData(layout), [layout])
    const canvasHeight = dimensions.plotTop + dimensions.plotHeight
    useEffect(() => {
        setNodes(nodes, canvasHeight)
    }, [nodes, canvasHeight, setNodes])

    return (
        <>
            {resolvedNodeCards.map((node) => (
                <PathNodeCard
                    key={node.index}
                    node={node}
                    insightProps={insightProps}
                    canvasHeight={canvasHeight}
                    popoverVisible={cardPopoverIndex === node.index}
                    onMouseEnter={() => hoverCard(node.index)}
                    onMouseLeave={unhoverCard}
                />
            ))}
        </>
    )
}
