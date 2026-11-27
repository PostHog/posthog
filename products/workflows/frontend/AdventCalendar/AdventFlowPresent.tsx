import { useEffect } from 'react'

import { AdventPresent } from './AdventPresent'
import { AdventTicketCount } from './AdventTicketCount'
import { ADVENT_FLOW_OPENING_MS } from './flow/AdventFlowStage'
import { AdventFlowStep, AdventFlowStepProps } from './flow/AdventFlowStep'

export function AdventFlowPresent(step: AdventFlowStepProps): JSX.Element {
    const { node, isOpening, onOpened } = step
    const { tile } = node

    useEffect(() => {
        if (!isOpening) {
            return
        }
        const timer = window.setTimeout(onOpened, ADVENT_FLOW_OPENING_MS)
        return () => window.clearTimeout(timer)
    }, [isOpening, onOpened])

    return (
        <>
            <AdventFlowStep {...step} face={<AdventPresent className="size-12" />} />
            <span
                className="AdventFlowPresent__count"
                style={{
                    left: tile.x + tile.width / 2,
                    top: node.door?.status === 'open' ? tile.y : tile.y + tile.height,
                }}
            >
                <AdventTicketCount />
            </span>
        </>
    )
}
