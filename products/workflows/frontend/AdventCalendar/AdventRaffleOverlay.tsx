import { useActions, useValues } from 'kea'
import { useEffect, useRef, useState } from 'react'

import { adventCalendarLogic } from './adventCalendarLogic'
import { ADVENT_LAST_DAY, ADVENT_YEAR } from './adventContent'
import { AdventPoint } from './adventGraph'
import { AdventTicketFlight } from './AdventTicketFlight'
import { ADVENT_FLOW_EXIT_ID, AdventFlowLayout, AdventFlowRect } from './flow/adventFlowLayout'
import { AdventFlowView } from './flow/AdventFlowStage'

const centerOf = ({ x, y, width, height }: AdventFlowRect): AdventPoint => ({ x: x + width / 2, y: y + height / 2 })

export function AdventRaffleOverlay({
    view,
    layout,
}: {
    view: AdventFlowView
    layout: AdventFlowLayout
}): JSX.Element | null {
    const { ticketFlight, selectedDoorId, localDate } = useValues(adventCalendarLogic)
    const { landTicket } = useActions(adventCalendarLogic)
    const latestView = useRef(view)
    latestView.current = view
    const [shownDay, setShownDay] = useState<number | null>(null)
    const present = layout.nodes.find((node) => node.door?.day === ADVENT_LAST_DAY)
    const source = layout.nodes.find((node) => node.door?.day === ticketFlight && node.door.status === 'open')
    const isHeldByCard = layout.orientation === 'column' && !!selectedDoorId
    const presentId = present?.id ?? null
    const flightDay = !isHeldByCard && presentId ? ticketFlight : null
    const isOver = localDate > new Date(ADVENT_YEAR, 11, ADVENT_LAST_DAY).getTime()

    useEffect(() => {
        if (isOver) {
            latestView.current.showNode(ADVENT_FLOW_EXIT_ID)
        }
    }, [isOver])

    useEffect(() => {
        if (flightDay === null || presentId === null) {
            setShownDay(null)
            return
        }
        latestView.current.showNode(presentId)
        const frame = requestAnimationFrame(() => setShownDay(flightDay))
        return () => cancelAnimationFrame(frame)
    }, [flightDay, presentId])

    if (shownDay === null || shownDay !== flightDay || !present || !source) {
        return null
    }
    const from = view.toStage(centerOf(source.tile))
    return (
        <AdventTicketFlight
            key={shownDay}
            from={{ x: from.x, y: Math.max(0, from.y) }}
            to={view.toStage(centerOf(present.tile))}
            onLand={landTicket}
        />
    )
}
