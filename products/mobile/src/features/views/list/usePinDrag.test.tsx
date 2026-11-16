import 'react-native-gesture-handler/jestSetup'
import { act, fireEvent, render, renderHook } from '@testing-library/react-native'
import { Text, type ViewInstance } from 'react-native'
import { PointerType, State } from 'react-native-gesture-handler'

import type { PinView } from '@/model/views'
import { PinDragTile } from './PinDragOverlay'
import { type PinDrag, usePinDrag } from './usePinDrag'

jest.mock('react-native-reanimated', () => ({
    useSharedValue: (value: number) => {
        const { useRef } = jest.requireActual<typeof import('react')>('react')
        return useRef({ value }).current
    },
}))
jest.mock('react-native-worklets', () => ({ scheduleOnUI: (worklet: () => void) => worklet() }))
jest.mock('@/lib/haptics', () => ({ haptic: jest.fn() }))

const chartId = 'a'
const pins: PinView[] = [chartId, 'b', 'c'].map((id) => ({
    shortcutId: id,
    shortcutIds: [id],
    kind: 'insight',
    ref: id,
    name: id,
    href: `/insights/${id}`,
    rank: null,
    serverOrder: 0,
    display: { mode: 'row' },
}))

type StartEvent = Parameters<NonNullable<PinDrag['gesture']['handlers']['onStart']>>[0]
function event(y: number): StartEvent {
    return {
        handlerTag: 1,
        state: State.ACTIVE,
        oldState: State.BEGAN,
        numberOfPointers: 1,
        pointerType: PointerType.TOUCH,
        x: 50,
        y,
        absoluteX: 50,
        absoluteY: y,
        translationX: 0,
        translationY: 0,
        velocityX: 0,
        velocityY: 0,
    }
}

function pickup(drag: PinDrag, y = 120): void {
    const touch = { id: 1, x: 50, y, absoluteX: 50, absoluteY: y }
    drag.gesture.handlers.onTouchesDown?.(
        {
            handlerTag: 1,
            state: State.BEGAN,
            numberOfTouches: 1,
            pointerType: PointerType.TOUCH,
            eventType: 1,
            allTouches: [touch],
            changedTouches: [touch],
        },
        { handlerTag: 1, begin: jest.fn(), activate: jest.fn(), end: jest.fn(), fail: jest.fn() }
    )
    // Native recognition supplies ACTIVE only after the extra-long hold; simulator coverage checks that timing.
    drag.gesture.handlers.onStart?.(event(y))
}

function setup(tileTop = (index: number): number => 100 + index * 100) {
    const reorder = jest.fn()
    const metrics = { current: { offset: 0, contentHeight: 1000, viewportHeight: 500 } }
    const scrollTo = jest.fn((offset: number) => {
        metrics.current.offset = offset
    })
    const options = {
        pins,
        enabled: true,
        scope: 'project-one',
        width: 400,
        top: 80,
        bottom: 80,
        metrics,
        scrollTo,
        onStart: jest.fn(),
        onReorder: reorder,
    }
    const hook = renderHook((props: Parameters<typeof usePinDrag>[0]) => usePinDrag(props), { initialProps: options })
    act(() => {
        pins.forEach((pin, index) => {
            hook.result.current.register(pin.shortcutId, {
                measureInWindow: (callback: (x: number, y: number, width: number, height: number) => void) =>
                    callback(20, tileTop(index), 360, 80),
            } as unknown as ViewInstance)
        })
    })
    return { ...hook, options, reorder, scrollTo }
}

beforeEach(() => jest.useFakeTimers())
afterEach(() => jest.useRealTimers())

test('saves only on drop and preserves the pins between source and destination', () => {
    const { result, reorder } = setup()
    act(() => pickup(result.current))
    act(() => result.current.gesture.handlers.onUpdate?.(event(320)))
    expect(result.current.dragged?.shortcutId).toBe('a')
    expect(reorder).not.toHaveBeenCalled()
    act(() => result.current.gesture.handlers.onFinalize?.(event(320), true))
    expect(reorder).toHaveBeenCalledWith(['b', 'c', 'a'])
    expect(result.current.dragged).toBeNull()
})

test('picks up the tile below a chart after the chart grows', () => {
    let extraHeight = 0
    const { result } = setup((index) => 100 + index * 100 + (index > 0 ? extraHeight : 0))
    const chart = render(
        <PinDragTile id={chartId} drag={result.current}>
            <Text>Chart</Text>
        </PinDragTile>
    )
    extraHeight = 100
    fireEvent(chart.getByText('Chart'), 'layout')
    act(() => jest.advanceTimersByTime(32))
    act(() => pickup(result.current, 320))
    expect(result.current.dragged?.shortcutId).toBe('b')
})

test.each(['cancel', 'stationary', 'refresh', 'scope', 'disabled'] as const)(
    '%s does not save a stale or unchanged order',
    (reason) => {
        const { result, rerender, options, reorder } = setup()
        act(() => pickup(result.current))
        if (reason !== 'stationary') act(() => result.current.gesture.handlers.onUpdate?.(event(320)))
        if (reason === 'refresh') rerender({ ...options, pins: pins.slice(1) })
        if (reason === 'scope') rerender({ ...options, scope: 'project-two' })
        if (reason === 'disabled') rerender({ ...options, enabled: false })
        act(() => result.current.gesture.handlers.onFinalize?.(event(320), reason !== 'cancel'))
        expect(reorder).not.toHaveBeenCalled()
        expect(result.current.dragged).toBeNull()
    }
)

test('edge scrolling stops at the last pin and after cancellation', () => {
    const { result, scrollTo } = setup()
    act(() =>
        result.current.register('c', {
            measureInWindow: (callback: (x: number, y: number, width: number, height: number) => void) =>
                callback(20, 900, 360, 80),
        } as unknown as ViewInstance)
    )
    act(() => pickup(result.current))
    act(() => jest.advanceTimersByTime(64))
    expect(scrollTo).not.toHaveBeenCalled()
    act(() => result.current.gesture.handlers.onUpdate?.(event(420)))
    act(() => jest.advanceTimersByTime(64))
    expect(scrollTo).toHaveBeenCalled()
    act(() =>
        result.current.register('c', {
            measureInWindow: (callback: (x: number, y: number, width: number, height: number) => void) =>
                callback(20, 340, 360, 80),
        } as unknown as ViewInstance)
    )
    scrollTo.mockClear()
    act(() => jest.advanceTimersByTime(64))
    expect(scrollTo).not.toHaveBeenCalled()
    act(() => result.current.gesture.handlers.onFinalize?.(event(420), false))
    scrollTo.mockClear()
    act(() => jest.advanceTimersByTime(64))
    expect(scrollTo).not.toHaveBeenCalled()
})
