import { useActions, useValues } from 'kea'
import { RefObject, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

import { Button } from '@posthog/quill'

import { getHedgehogModeAssetsUrl } from 'lib/components/HedgehogMode/HedgehogMode'

import type { SeasonalChecklist } from './seasonalChecklist'
import { HOG_SIZE, HogWorld, SeasonalHog } from './seasonalHog'
import { HogSprites, loadHogSprites } from './seasonalHogSprites'
import { SeasonalSnow } from './seasonalSnow'
import { todaySeasonalChecklistLogic } from './todaySeasonalChecklistLogic'

const GROUND_GAP = 6

function prefersReducedMotion(): boolean {
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function TodaySeasonalHog({
    checklist,
    cardRef,
}: {
    checklist: SeasonalChecklist
    cardRef: RefObject<HTMLDivElement>
}): JSX.Element | null {
    const { isOpen, dismissed, allDone, doneCount } = useValues(todaySeasonalChecklistLogic)
    const { openChecklist } = useActions(todaySeasonalChecklistLogic)
    const [sprites, setSprites] = useState<HogSprites | null>(null)
    const [spritesFailed, setSpritesFailed] = useState(false)
    const anchorRef = useRef<HTMLDivElement>(null)
    const canvasRef = useRef<HTMLCanvasElement>(null)
    const buttonRef = useRef<HTMLButtonElement>(null)
    const bubbleRef = useRef<HTMLDivElement>(null)
    const hogRef = useRef<SeasonalHog | null>(null)
    const snowRef = useRef(new SeasonalSnow())
    const stateRef = useRef({ isOpen, dismissed, allDone, doneCount, opened: false })

    useEffect(() => {
        let cancelled = false
        loadHogSprites(getHedgehogModeAssetsUrl()).then(
            (loaded) => !cancelled && setSprites(loaded),
            () => !cancelled && setSpritesFailed(true)
        )
        return () => {
            cancelled = true
        }
    }, [])

    useEffect(() => {
        const hog = hogRef.current
        const previous = stateRef.current
        const letItSnow = (): void => {
            if (checklist.snow && !prefersReducedMotion()) {
                snowRef.current.start(performance.now())
            }
        }
        if (hog) {
            if (isOpen && !previous.isOpen) {
                hog.jumpToCard()
                letItSnow()
            } else if (!isOpen && previous.isOpen) {
                hog.jumpToGround()
            }
            if (dismissed && !previous.dismissed) {
                hog.leave()
            } else if (!dismissed && previous.dismissed) {
                hog.enter()
            }
            if (doneCount > previous.doneCount && isOpen) {
                if (allDone) {
                    hog.celebrate()
                    letItSnow()
                } else {
                    hog.wave()
                }
            }
        }
        stateRef.current = { isOpen, dismissed, allDone, doneCount, opened: previous.opened || isOpen }
    }, [isOpen, dismissed, allDone, doneCount, checklist.snow])

    useEffect(() => {
        const canvas = canvasRef.current
        const context = canvas?.getContext('2d')
        if (!sprites || !canvas || !context) {
            return
        }
        const reducedMotion = prefersReducedMotion()
        const world = (): HogWorld => {
            const page = anchorRef.current?.parentElement?.getBoundingClientRect()
            return {
                ground: window.innerHeight - GROUND_GAP,
                left: page?.left ?? 0,
                right: page?.right ?? window.innerWidth,
                card: stateRef.current.isOpen ? (cardRef.current?.getBoundingClientRect() ?? null) : null,
                reducedMotion,
            }
        }
        if (!hogRef.current) {
            hogRef.current = new SeasonalHog(world())
            if (stateRef.current.dismissed) {
                hogRef.current.state = 'away'
            } else if (stateRef.current.isOpen) {
                hogRef.current.jumpToCard()
            }
        }
        const hog = hogRef.current
        const resize = (): void => {
            const ratio = window.devicePixelRatio || 1
            canvas.width = window.innerWidth * ratio
            canvas.height = window.innerHeight * ratio
            context.setTransform(ratio, 0, 0, ratio, 0, 0)
        }
        resize()
        window.addEventListener('resize', resize)

        let frame = 0
        const tick = (): void => {
            const current = world()
            hog.step(current, sprites)
            snowRef.current.step(performance.now(), window.innerWidth, window.innerHeight)
            context.clearRect(0, 0, window.innerWidth, window.innerHeight)
            snowRef.current.draw(context, current.card)
            hog.draw(context, sprites, checklist.accessories)

            const visible = hog.state !== 'away' && hog.state !== 'leave'
            const button = buttonRef.current
            if (button) {
                button.hidden = !visible
                button.style.transform = `translate(${hog.x - HOG_SIZE / 2 + 10}px, ${hog.y - HOG_SIZE + 6}px)`
            }
            const bubble = bubbleRef.current
            if (bubble) {
                bubble.hidden = !visible || hog.state !== 'roam' || stateRef.current.opened
                bubble.style.transform = `translate(calc(${hog.x}px - 50%), calc(${hog.y - HOG_SIZE}px - 100%))`
            }
            frame = requestAnimationFrame(tick)
        }
        frame = requestAnimationFrame(tick)
        return () => {
            cancelAnimationFrame(frame)
            window.removeEventListener('resize', resize)
        }
    }, [sprites, checklist.accessories, cardRef])

    if (spritesFailed) {
        return dismissed ? null : (
            <div className="mb-8 flex">
                <Button variant="outline" onClick={openChecklist} data-attr="today-seasonal-checklist-open">
                    {checklist.bubble}
                </Button>
            </div>
        )
    }

    return (
        <>
            <div ref={anchorRef} hidden />
            {sprites
                ? createPortal(
                      <div data-quill className="TodaySeasonalHog">
                          <canvas ref={canvasRef} className="TodaySeasonalHog__canvas" aria-hidden="true" />
                          <div ref={bubbleRef} className="TodaySeasonalHog__bubble" hidden aria-hidden="true">
                              {checklist.bubble}
                          </div>
                          <button
                              ref={buttonRef}
                              type="button"
                              className="TodaySeasonalHog__button"
                              aria-label={checklist.bubble}
                              onClick={isOpen ? undefined : openChecklist}
                              onPointerEnter={(event) => hogRef.current?.hover(true, event.clientX)}
                              onPointerLeave={(event) => hogRef.current?.hover(false, event.clientX)}
                              hidden
                              data-attr="today-seasonal-hog"
                          />
                      </div>,
                      document.body
                  )
                : null}
        </>
    )
}
