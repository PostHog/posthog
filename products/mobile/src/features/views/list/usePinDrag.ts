import { type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { AppState, type View } from 'react-native'
import { Gesture, type PanGesture } from 'react-native-gesture-handler'
import { type SharedValue, useSharedValue } from 'react-native-reanimated'
import { scheduleOnUI } from 'react-native-worklets'

import { haptic } from '@/lib/haptics'
import type { PinView } from '@/model/views'
import { dragScrollStep, dropPin, nearestPin, type PinFrame } from './pinDrag'

const HOLD_MS = 1300
const HEAD_HEIGHT = 64

interface Options {
    pins: readonly PinView[]
    enabled: boolean
    scope: string
    width: number
    top: number
    bottom: number
    metrics: { current: { offset: number; contentHeight: number; viewportHeight: number } }
    scrollTo: (y: number) => void
    onStart: () => void
    onReorder: (ids: string[]) => void
}

interface Drag {
    pin: PinView
    ids: string[]
    target: string
    startX: number
    startY: number
    moved: boolean
    x: number
    y: number
}

/** The recognizer belongs to the list, so recycling the source tile cannot end an edge-scrolling drag. */
export interface PinDrag {
    gesture: PanGesture
    root: RefObject<View | null>
    dragged: PinView | null
    register: (id: string, node: View | null) => void
    measure: (id: string) => void
    measureAll: () => void
    x: SharedValue<number>
    y: SharedValue<number>
    targetX: SharedValue<number>
    targetY: SharedValue<number>
    targetWidth: SharedValue<number>
    targetHeight: SharedValue<number>
}

export function usePinDrag(options: Options): PinDrag {
    const latest = useRef(options)
    latest.current = options
    const nodes = useRef(new Map<string, View>())
    const frames = useRef(new Map<string, PinFrame & { offset: number }>())
    const root = useRef<View>(null)
    const origin = useRef({ x: 0, y: 0 })
    const candidate = useRef<string | null>(null)
    const active = useRef<Drag | null>(null)
    const [dragged, setDragged] = useState<PinView | null>(null)
    const x = useSharedValue(0)
    const y = useSharedValue(0)
    const targetX = useSharedValue(0)
    const targetY = useSharedValue(0)
    const targetWidth = useSharedValue(0)
    const targetHeight = useSharedValue(0)

    const measure = useCallback((id: string): void => {
        const node = nodes.current.get(id)
        const offset = latest.current.metrics.current.offset
        node?.measureInWindow((x, y, width, height) => {
            if (nodes.current.get(id) === node && width > 0 && height > 0) {
                frames.current.set(id, { id, x, y, width, height, offset })
            }
        })
    }, [])
    const register = useCallback(
        (id: string, node: View | null): void => {
            if (node) {
                nodes.current.set(id, node)
                measure(id)
            } else {
                nodes.current.delete(id)
                frames.current.delete(id)
            }
        },
        [measure]
    )
    const measureAll = useCallback((): void => {
        root.current?.measureInWindow((x, y) => {
            origin.current = { x, y }
        })
        for (const id of nodes.current.keys()) measure(id)
    }, [measure])
    const visibleFrames = useCallback((): PinFrame[] => {
        const { offset } = latest.current.metrics.current
        const ids = new Set(latest.current.pins.map((pin) => pin.shortcutId))
        return [...frames.current.values()]
            .filter((frame) => ids.has(frame.id))
            .map((frame) => ({ ...frame, y: frame.y + frame.offset - offset }))
    }, [])
    const update = useCallback(
        (absoluteX: number, absoluteY: number): void => {
            const drag = active.current
            if (!drag) return
            drag.moved ||= Math.hypot(absoluteX - drag.startX, absoluteY - drag.startY) > 8
            drag.x = absoluteX
            drag.y = absoluteY
            x.value = absoluteX - origin.current.x
            y.value = absoluteY - origin.current.y
            const frames = visibleFrames()
            const frame = drag.moved
                ? nearestPin(frames, absoluteX, absoluteY)
                : frames.find((frame) => frame.id === drag.pin.shortcutId)
            if (!frame) return
            if (drag.target !== frame.id) haptic('selection')
            drag.target = frame.id
            targetX.value = frame.x - origin.current.x
            targetY.value = frame.y - origin.current.y
            targetWidth.value = frame.width
            targetHeight.value = frame.height
        },
        [visibleFrames, x, y, targetX, targetY, targetWidth, targetHeight]
    )
    const finish = useCallback((save: boolean): void => {
        const drag = active.current
        active.current = null
        candidate.current = null
        setDragged(null)
        if (!save || !drag?.moved) return
        const ids = latest.current.pins.map((pin) => pin.shortcutId)
        // A refresh, project switch, or another ordering action must never be overwritten by an old gesture.
        if (ids.length !== drag.ids.length || ids.some((id, index) => id !== drag.ids[index])) return
        const next = dropPin(ids, drag.pin.shortcutId, drag.target)
        if (next.some((id, index) => id !== ids[index])) latest.current.onReorder(next)
    }, [])
    const gesture = useMemo(
        () =>
            Gesture.Pan()
                .enabled(options.enabled && options.pins.length > 1)
                .activateAfterLongPress(HOLD_MS)
                .maxPointers(1)
                .runOnJS(true)
                .onTouchesDown((event, manager) => {
                    const touch = event.allTouches[0]
                    if (!touch || event.numberOfTouches !== 1) {
                        candidate.current = null
                        scheduleOnUI(manager.fail)
                        return
                    }
                    const frame = visibleFrames().find(
                        (frame) =>
                            touch.absoluteX >= frame.x &&
                            touch.absoluteX <= frame.x + frame.width &&
                            touch.absoluteY >= frame.y &&
                            touch.absoluteY <= frame.y + Math.min(HEAD_HEIGHT, frame.height)
                    )
                    candidate.current = frame?.id ?? null
                    if (!frame) scheduleOnUI(manager.fail)
                })
                .onStart((event) => {
                    const pin = latest.current.pins.find((pin) => pin.shortcutId === candidate.current)
                    if (!pin || !latest.current.enabled) return
                    active.current = {
                        pin,
                        ids: latest.current.pins.map((pin) => pin.shortcutId),
                        target: pin.shortcutId,
                        startX: event.absoluteX,
                        startY: event.absoluteY,
                        moved: false,
                        x: event.absoluteX,
                        y: event.absoluteY,
                    }
                    latest.current.onStart()
                    setDragged(pin)
                    haptic('light')
                    update(event.absoluteX, event.absoluteY)
                })
                .onUpdate((event) => update(event.absoluteX, event.absoluteY))
                .onFinalize((_event, success) => finish(success)),
        [options.enabled, options.pins.length, visibleFrames, update, finish]
    )

    useEffect(() => {
        if (!dragged) return
        const timer = setInterval(() => {
            const drag = active.current
            if (!drag?.moved) return
            const { metrics, top, bottom, scrollTo } = latest.current
            const delta = dragScrollStep(
                drag.y,
                origin.current.y + top,
                origin.current.y + metrics.current.viewportHeight - bottom
            )
            const bottomLimit = origin.current.y + metrics.current.viewportHeight - bottom
            const lastId = latest.current.pins.at(-1)?.shortcutId
            const last = visibleFrames().find((frame) => frame.id === lastId)
            const maxOffset = Math.min(
                metrics.current.contentHeight - metrics.current.viewportHeight,
                last ? metrics.current.offset + last.y + last.height - bottomLimit : Number.POSITIVE_INFINITY
            )
            // Stop at the final pin, rather than carrying a held tile into Recent and Browse.
            const next =
                delta > 0
                    ? Math.max(metrics.current.offset, Math.min(maxOffset, metrics.current.offset + delta))
                    : Math.max(0, metrics.current.offset + delta)
            if (delta !== 0 && next !== metrics.current.offset) scrollTo(next)
            update(drag.x, drag.y)
        }, 16)
        return () => clearInterval(timer)
    }, [dragged, update, visibleFrames])
    // Cancel on navigation, search, rotation, project changes, backgrounding, and unmount.
    useEffect(() => {
        void options.scope
        void options.width
        void options.enabled
        finish(false)
        return () => {
            active.current = null
            candidate.current = null
        }
    }, [options.scope, options.width, options.enabled, finish])
    useEffect(() => {
        const subscription = AppState.addEventListener('change', (state) => {
            if (state !== 'active') finish(false)
        })
        return () => subscription.remove()
    }, [finish])

    return { gesture, root, dragged, register, measure, measureAll, x, y, targetX, targetY, targetWidth, targetHeight }
}
