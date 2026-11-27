import { AnimationEvent, CSSProperties } from 'react'

import { AdventPoint } from './adventGraph'
import { AdventTicketIcon } from './AdventTicketIcon'

const ARC_HEIGHT = 70

export interface AdventTicketFlightProps {
    from: AdventPoint
    to: AdventPoint
    onLand: () => void
}

export function AdventTicketFlight({ from, to, onLand }: AdventTicketFlightProps): JSX.Element {
    const dy = from.y - to.y
    const style = {
        left: to.x,
        top: to.y,
        '--advent-fly-dx': `${from.x - to.x}px`,
        '--advent-fly-dy': `${dy}px`,
        '--advent-fly-peak': `${Math.min(dy, 0) - ARC_HEIGHT}px`,
    } as CSSProperties
    const land = (event: AnimationEvent): void => {
        if (event.target === event.currentTarget) {
            onLand()
        }
    }
    return (
        <span className="AdventTicketFlight" style={style} onAnimationEnd={land} data-attr="advent-ticket-flight">
            <span className="AdventTicketFlight__arc">
                <AdventTicketIcon className="h-7 w-12" />
            </span>
        </span>
    )
}
