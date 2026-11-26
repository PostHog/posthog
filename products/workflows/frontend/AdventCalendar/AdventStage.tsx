import './AdventCalendar.scss'

import { ReactFlowProvider } from '@xyflow/react'
import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { cn } from 'lib/utils/css-classes'

import { adventCalendarLogic } from './adventCalendarLogic'
import { AdventCanvas } from './AdventCanvas'
import { AdventCardFace, AdventDoorCard } from './AdventDoorCard'
import { ADVENT_DOOR_SIZE, AdventDoor, adventDoorGround, adventHogSize } from './adventGraph'
import { adventPaletteStyle } from './adventPalette'
import { AdventPictureBackdrop } from './AdventPictureBackdrop'
import { useAdventCard } from './useAdventCard'
import { useAdventEscape } from './useAdventEscape'
import { useAdventReveal } from './useAdventReveal'
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
    const { graph, today, selectedDoor, revealingDoor } = useValues(adventCalendarLogic)
    const { activateDoor, answerDoor, clearSelection, finishReveal, clickTip } = useActions(adventCalendarLogic)
    const fit = useAdventStageFit()
    const { ref, zoom, box, stage } = fit
    const revealingDoorId = revealingDoor?.id ?? null
    const selectedDoorId = selectedDoor?.id ?? null
    const reveal = useAdventReveal(revealingDoorId, finishReveal)
    const card = useAdventCard(selectedDoorId, !revealingDoor)
    const cardDoor = revealingDoor ? null : (graph.doors.find((door) => door.id === card.doorId) ?? null)
    const { clearHover } = card

    const dismiss = useCallback((): void => {
        clearSelection()
        clearHover()
    }, [clearSelection, clearHover])
    useAdventEscape(!!revealingDoor, finishReveal, dismiss)

    return (
        <div
            ref={ref}
            className={cn('AdventStage', reveal.phase && 'AdventStage--revealing')}
            style={adventPaletteStyle()}
            data-attr="advent-stage"
        >
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
                                openingDoorId={revealingDoorId}
                                onActivateDoor={activateDoor}
                                onEnterDoor={card.onEnterDoor}
                                onLeaveDoor={card.onLeaveDoor}
                                onPaneClick={dismiss}
                            />
                        </ReactFlowProvider>
                    </div>
                    {reveal.phase && (
                        <button
                            type="button"
                            className="AdventStage__scrim"
                            aria-label="Continue"
                            onClick={reveal.advance}
                        />
                    )}
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
