import './AdventCalendar.scss'

import { useValues } from 'kea'
import { useCallback, useMemo } from 'react'

import { adventCalendarLogic } from './adventCalendarLogic'
import { AdventFlowPresent } from './AdventFlowPresent'
import { AdventRaffleOverlay } from './AdventRaffleOverlay'
import { AdventFlowEdge } from './flow/adventFlowLayout'
import { AdventFlowStage } from './flow/AdventFlowStage'
import { AdventFlowExitNote } from './flow/AdventFlowStep'

const EXIT_NOTE: AdventFlowExitNote = {
    caption: 'Raffle draw',
    body: 'Winners are drawn after December 24 and hear from us by email within a few days. Make sure to check your inbox.',
}

export function AdventRaffleFlowStage(): JSX.Element {
    const { graph, ticketDays } = useValues(adventCalendarLogic)
    const earning = useMemo(
        () =>
            new Set(
                graph.doors
                    .filter((door) => door.status === 'open' && ticketDays.includes(door.day))
                    .map((door) => door.id)
            ),
        [graph, ticketDays]
    )
    const isEdgeEmphasized = useCallback((edge: AdventFlowEdge) => earning.has(edge.target), [earning])
    return (
        <AdventFlowStage
            renderLastDoor={(step) => <AdventFlowPresent {...step} />}
            isEdgeEmphasized={isEdgeEmphasized}
            renderOverlay={(view, layout) => <AdventRaffleOverlay view={view} layout={layout} />}
            exitNote={EXIT_NOTE}
        />
    )
}
