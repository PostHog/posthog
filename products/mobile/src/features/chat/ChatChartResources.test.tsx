import { notifyManager, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, waitFor } from '@testing-library/react-native'
import * as router from 'expo-router'
import { ScrollView, View, type ViewInstance } from 'react-native'
import { runQuery } from '@/api/query'
import { viewsQueue } from '@/features/views/refreshQueue'
import { abortError } from '@/lib/abort'
import * as canvasBudget from '@/ui/chart/budget/ChartCanvasBudget'
import { ChatChartResources, ChatChartRow, useChatChartViewport } from './ChatChartResources'
import { ChatVisualization } from './ChatVisualization'

jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => ({ host: 'https://example.com', projectId: 42 }) }))
jest.mock('@/api/query', () => ({ ...jest.requireActual('@/api/query'), runQuery: jest.fn() }))
jest.mock('expo-router', () => ({ ...jest.requireActual('expo-router'), useIsFocused: jest.fn(() => true) }))

const result = [{ data: [12, 15], days: ['2026-10-01', '2026-10-02'] }]
notifyManager.setNotifyFunction((callback) => act(callback))
let client: QueryClient
let flushFrames: () => void

function Cards({ count, supplied, events }: { count: number; supplied: boolean; events?: (string | null)[] }) {
    const viewport = useChatChartViewport()
    return (
        <ScrollView testID="chart-viewport" onLayout={viewport.onLayout} onScroll={viewport.onScroll}>
            <ChatChartRow rowKey="long-message" index={0}>
                {Array.from({ length: count }, (_, index) => ({
                    id: `card-${index}`,
                    event: events ? events[index] : `event-${index}`,
                })).map(({ id, event }) =>
                    event ? (
                        <ChatVisualization
                            key={id}
                            title={event.replace('event-', 'Chart ')}
                            query={{ kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event }] }}
                            result={supplied ? result : undefined}
                        />
                    ) : null
                )}
            </ChatChartRow>
        </ScrollView>
    )
}

function tree(count: number, supplied: boolean, events?: (string | null)[]) {
    return (
        <QueryClientProvider client={client}>
            <ChatChartResources>
                <Cards count={count} supplied={supplied} events={events} />
            </ChatChartResources>
        </QueryClientProvider>
    )
}

function view(count: number, supplied: boolean, events?: (string | null)[]) {
    const screen = render(tree(count, supplied, events))
    const cards = screen.getAllByTestId('chat-visualization')
    cards.forEach((card) => {
        fireEvent(card, 'layout', { nativeEvent: { layout: { y: 0, height: 200 } } })
    })
    const row = screen.getByTestId('chart-viewport').findByProps({ collapsable: false })
    fireEvent(row, 'layout', { nativeEvent: { layout: { y: 0, height: count * 240 } } })
    flushFrames()
    return screen
}

function scroll(screen: ReturnType<typeof render>, offset: number, height: number): void {
    fireEvent(screen.getByTestId('chart-viewport'), 'scroll', {
        nativeEvent: { contentOffset: { y: offset }, layoutMeasurement: { height } },
    })
}

beforeEach(() => {
    jest.clearAllMocks()
    jest.mocked(router.useIsFocused).mockReturnValue(true)
    viewsQueue.reset()
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
    const frames = new Map<number, Parameters<typeof requestAnimationFrame>[0]>()
    let frameId = 0
    jest.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((callback) => {
        frames.set(++frameId, callback)
        return frameId
    })
    jest.spyOn(globalThis, 'cancelAnimationFrame').mockImplementation((id) => {
        if (typeof id === 'number') frames.delete(id)
    })
    flushFrames = () =>
        act(() => {
            const callbacks = [...frames.values()]
            frames.clear()
            for (const callback of callbacks) callback(0)
        })
    const positions = new WeakMap<object, number>()
    let index = 0
    jest.spyOn(View.prototype as ViewInstance, 'measureLayout').mockImplementation(function (
        this: object,
        _ancestor,
        complete
    ) {
        if (!positions.has(this)) positions.set(this, index++ * 240)
        complete(0, positions.get(this) ?? 0, 320, 200)
    })
})
afterEach(() => {
    viewsQueue.reset()
    client.clear()
    jest.restoreAllMocks()
})

test('gives later charts in one tall message native canvases when they enter the viewport', () => {
    const screen = view(10, true)
    scroll(screen, 0, 480)
    expect(screen.getByLabelText('Chart 0 chart')).toBeTruthy()
    expect(screen.queryByLabelText('Chart 9 chart')).toBeNull()
    expect(screen.getAllByTestId('chat-visualization-chart').length).toBeLessThanOrEqual(6)
    scroll(screen, 1920, 480)
    expect(screen.getByLabelText('Chart 9 chart')).toBeTruthy()
    expect(screen.queryByLabelText('Chart 0 chart')).toBeNull()
    expect(screen.getAllByTestId('chat-visualization-chart').length).toBeLessThanOrEqual(6)
})

test('reads only visible cards, runs two at once and drops queued reads after scrolling past them', async () => {
    const started: number[] = []
    const pending = new Map<number, () => void>()
    jest.mocked(runQuery).mockImplementation((query, options) => {
        const index = Number((query as { series: { event: string }[] }).series[0]?.event.split('-')[1])
        started.push(index)
        return new Promise((resolve, reject) => {
            pending.set(index, () => resolve({ results: result }))
            options?.signal?.addEventListener('abort', () => reject(abortError()), { once: true })
        })
    })
    const screen = view(5, false)
    expect(started).toEqual([])
    scroll(screen, 0, 720)
    await waitFor(() => expect(started).toEqual([0, 1]))
    scroll(screen, 960, 240)
    await act(async () => {
        pending.get(0)?.()
        pending.get(1)?.()
    })
    await waitFor(() => expect(started).toEqual([0, 1, 4]))
    await act(async () => {
        pending.get(4)?.()
    })
    await waitFor(() => expect(screen.getByLabelText('Chart 4 chart')).toBeTruthy())
})

function controlledReads(ignoreAbort = false) {
    const started: string[] = []
    const pending = new Map<number, (value: unknown) => void>()
    jest.mocked(runQuery).mockImplementation((query, options) => {
        const event = (query as { series: { event: string }[] }).series[0]?.event ?? ''
        const index = started.push(event) - 1
        return new Promise((resolve, reject) => {
            pending.set(index, resolve)
            if (!ignoreAbort) options?.signal?.addEventListener('abort', () => reject(abortError()), { once: true })
        })
    })
    return {
        started,
        finish: async (...indices: number[]) =>
            act(async () => {
                for (const index of indices) pending.get(index)?.({ results: result })
            }),
    }
}

test.each([false, true])(
    'keeps a shared queued read only while a duplicate observer remains: %s',
    async (remaining) => {
        const reads = controlledReads()
        const screen = view(4, false, ['event-0', 'event-1', 'event-2', 'event-2'])
        scroll(screen, 0, 1200)
        await waitFor(() => expect(reads.started).toEqual(['event-0', 'event-1']))
        await act(async () =>
            screen.rerender(tree(4, false, ['event-0', 'event-1', null, remaining ? 'event-2' : null]))
        )
        flushFrames()
        await reads.finish(0, 1)
        if (remaining) {
            await waitFor(() => expect(reads.started).toEqual(['event-0', 'event-1', 'event-2']))
            await reads.finish(2)
            await waitFor(() => expect(screen.getByLabelText('Chart 2 chart')).toBeTruthy())
        } else expect(reads.started).toEqual(['event-0', 'event-1'])
    }
)

test.each([false, true])(
    'drops a superseded queued revision unless another observer still needs it: %s',
    async (duplicate) => {
        const reads = controlledReads()
        const screen = view(4, false, ['event-0', 'event-1', 'event-2', duplicate ? 'event-2' : null])
        scroll(screen, 0, 1200)
        await waitFor(() => expect(reads.started).toHaveLength(2))
        await act(async () =>
            screen.rerender(tree(4, false, ['event-0', 'event-1', 'event-3', duplicate ? 'event-2' : null]))
        )
        await reads.finish(0, 1)
        await waitFor(() =>
            expect(reads.started).toEqual(
                duplicate ? ['event-0', 'event-1', 'event-2', 'event-3'] : ['event-0', 'event-1', 'event-3']
            )
        )
        await reads.finish(2, 3)
        await waitFor(() => expect(screen.getByLabelText('Chart 3 chart')).toBeTruthy())
    }
)

test.each([false, true])('keeps running results for remounts but isolates a cleared cache: %s', async (clear) => {
    const reads = controlledReads(true)
    const first = view(1, false)
    scroll(first, 0, 480)
    await waitFor(() => expect(reads.started).toHaveLength(1))
    first.unmount()
    if (clear) {
        viewsQueue.reset()
        client.clear()
    }
    const next = view(1, false)
    scroll(next, 0, 720)
    if (clear) await waitFor(() => expect(reads.started).toHaveLength(2))
    await reads.finish(0)
    if (clear) {
        expect(next.queryByLabelText('Chart 0 chart')).toBeNull()
        await reads.finish(1)
    }
    await waitFor(() => expect(next.getByLabelText('Chart 0 chart')).toBeTruthy())
    expect(reads.started).toHaveLength(clear ? 2 : 1)
})

test.each(['inline', 'unfocused'] as const)('releases queued work when the observer becomes %s', async (reason) => {
    const reads = controlledReads()
    const screen = view(3, false)
    scroll(screen, 0, 1200)
    await waitFor(() => expect(reads.started).toHaveLength(2))
    if (reason === 'unfocused') jest.mocked(router.useIsFocused).mockReturnValue(false)
    await act(async () => screen.rerender(tree(3, reason === 'inline')))
    await reads.finish(0, 1)
    expect(reads.started).toEqual(['event-0', 'event-1'])
})

test('publishes one viewport update for a batch of card measurements', () => {
    const reports: (readonly string[])[] = []
    jest.spyOn(canvasBudget, 'useCanvasBudgetViewport').mockReturnValue({
        setVisibleKeys: (keys) => {
            reports.push(keys)
        },
        onViewableItemsChanged: () => undefined,
    })
    const screen = view(10, true)
    reports.length = 0
    const row = screen.getByTestId('chart-viewport').findByProps({ collapsable: false })
    fireEvent(row, 'layout', { nativeEvent: { layout: { y: 100, height: 2400 } } })
    expect(reports).toHaveLength(0)
    flushFrames()
    expect(reports).toHaveLength(1)
})
