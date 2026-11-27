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
import { AdventPictureCast, AdventPictureReveal } from './AdventPictureCast'
import { AdventSnow } from './AdventSnow'
import { AdventSnowPuffs } from './AdventSnowPuffs'
import { useAdventCard } from './useAdventCard'
import { useAdventEscape } from './useAdventEscape'
import { AdventRevealPhase, useAdventReveal } from './useAdventReveal'
import { AdventStageFit, useAdventStageFit } from './useAdventStageFit'
import { useAdventTrackScroll } from './useAdventTrackScroll'

function faceOf(door: AdventDoor, { zoom, box }: AdventStageFit, scrollLeft: number): AdventCardFace {
    const left = box.left - scrollLeft
    if (door.status !== 'open') {
        return { left: left + door.x * zoom, top: box.top + door.y * zoom, size: ADVENT_DOOR_SIZE * zoom, zoom }
    }
    const ground = adventDoorGround(door)
    const size = adventHogSize(door) * zoom
    return { left: left + ground.x * zoom - size / 2, top: box.top + ground.y * zoom - size, size, zoom }
}

function castReveal(
    door: AdventDoor | null,
    phase: AdventRevealPhase | null,
    zoom: number
): AdventPictureReveal | null {
    return door && phase ? { door, phase, zoom } : null
}

export function AdventStage(): JSX.Element {
    const { graph, today, selectedDoor, revealingDoor, snowPuffs, pollShares } = useValues(adventCalendarLogic)
    const { activateDoor, answerDoor, clearSelection, finishReveal, clickTip, clearSnowPuffs } =
        useActions(adventCalendarLogic)
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
    const { trackProps, scrollLeft } = useAdventTrackScroll({
        graph,
        today,
        fit,
        hasCard: !!cardDoor,
        onScrollAway: dismiss,
    })

    return (
        <div
            ref={ref}
            className={cn('AdventStage', reveal.phase && 'AdventStage--revealing')}
            style={adventPaletteStyle()}
            data-attr="advent-stage"
        >
            {zoom > 0 && (
                <>
                    <div {...trackProps}>
                        <div className="relative h-full" style={{ width: Math.max(stage.width, box.width) }}>
                            <div className="AdventPicture" style={box}>
                                <AdventPictureBackdrop graph={graph} hasTracks={false} />
                            </div>
                            <div className="AdventStage__workflow" {...(reveal.phase ? { inert: '' } : {})}>
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
                            <div className="AdventPicture AdventPicture--cast" style={box}>
                                <AdventPictureCast
                                    graph={graph}
                                    shares={pollShares}
                                    reveal={castReveal(revealingDoor, reveal.phase, zoom)}
                                    onActivateDoor={activateDoor}
                                    onEnterDoor={card.onEnterDoor}
                                    onLeaveDoor={card.onLeaveDoor}
                                />
                                <AdventSnowPuffs puffs={snowPuffs} onDone={clearSnowPuffs} />
                            </div>
                        </div>
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
                            shares={pollShares[cardDoor.day]}
                            face={faceOf(cardDoor, fit, scrollLeft())}
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
            <AdventSnow />
            <span className="AdventStage__grain" />
            <span className="AdventStage__frame" />
        </div>
    )
}
