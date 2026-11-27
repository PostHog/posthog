import './AdventCalendar.scss'

import { ReactFlowProvider } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { adventCalendarLogic } from './adventCalendarLogic'
import { AdventCanvas } from './AdventCanvas'
import { AdventCardFace, AdventDoorCard } from './AdventDoorCard'
import { ADVENT_DOOR_SIZE, AdventDoor, adventDoorGround, adventHogSize } from './adventGraph'
import { adventPaletteStyle } from './adventPalette'
import { AdventPictureBackdrop } from './AdventPictureBackdrop'
import { useAdventCard } from './useAdventCard'
import { useAdventEscape } from './useAdventEscape'
import { AdventStageFit, useAdventStageFit } from './useAdventStageFit'

function faceOf(door: AdventDoor, { zoom, box }: AdventStageFit): AdventCardFace {
    if (door.status !== 'open') {
        return { left: box.left + door.x * zoom, top: box.top + door.y * zoom, size: ADVENT_DOOR_SIZE * zoom, zoom }
    }
    const ground = adventDoorGround(door)
    const size = adventHogSize(door) * zoom
    return { left: box.left + ground.x * zoom - size / 2, top: box.top + ground.y * zoom - size, size, zoom }
}

export function AdventStage(): JSX.Element {
    const { graph, today, selectedDoor } = useValues(adventCalendarLogic)
    const { activateDoor, answerDoor, clearSelection, clickTip } = useActions(adventCalendarLogic)
    const fit = useAdventStageFit()
    const { ref, zoom, box, stage } = fit
    const selectedDoorId = selectedDoor?.id ?? null
    const card = useAdventCard(selectedDoorId, true)
    const cardDoor = graph.doors.find((door) => door.id === card.doorId) ?? null
    const { clearHover } = card

    const dismiss = useCallback((): void => {
        clearSelection()
        clearHover()
    }, [clearSelection, clearHover])
    useAdventEscape(dismiss)

    return (
        <div ref={ref} className="AdventStage" style={adventPaletteStyle()} data-attr="advent-stage">
            {zoom > 0 && (
                <>
                    <div className="AdventPicture" style={box}>
                        <AdventPictureBackdrop graph={graph} hasTracks={false} />
                    </div>
                    <div className="AdventStage__workflow">
                        <ReactFlowProvider>
                            <AdventCanvas
                                graph={graph}
                                viewport={{ x: box.left, y: box.top, zoom }}
                                today={today}
                                selectedDoorId={selectedDoorId}
                                onActivateDoor={activateDoor}
                                onEnterDoor={card.onEnterDoor}
                                onLeaveDoor={card.onLeaveDoor}
                                onPaneClick={dismiss}
                            />
                        </ReactFlowProvider>
                    </div>
                    {cardDoor && (
                        <AdventDoorCard
                            key={cardDoor.id}
                            door={cardDoor}
                            face={faceOf(cardDoor, fit)}
                            stage={stage}
                            isOpen={card.isOpen}
                            isPinned={card.isPinned}
                            onPin={activateDoor}
                            onAnswer={answerDoor}
                            onTipClick={clickTip}
                            onClose={dismiss}
                            onMouseEnter={card.onEnterCard}
                            onMouseLeave={card.onLeaveDoor}
                        />
                    )}
                </>
            )}
            <span className="AdventStage__grain" />
            <span className="AdventStage__frame" />
        </div>
    )
}
