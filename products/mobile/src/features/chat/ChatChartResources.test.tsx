import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, waitFor } from '@testing-library/react-native'
import { ScrollView, View, type ViewInstance } from 'react-native'
import { runQuery } from '@/api/query'
import { viewsQueue } from '@/features/views/refreshQueue'
import { abortError } from '@/lib/abort'
import { ChatChartResources, ChatChartRow, useChatChartViewport } from './ChatChartResources'
import { ChatVisualization } from './ChatVisualization'

jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => ({ host: 'https://example.com', projectId: 42 }) }))
jest.mock('@/api/query', () => ({ ...jest.requireActual('@/api/query'), runQuery: jest.fn() }))

const result = [{ data: [12, 15], days: ['2026-10-01', '2026-10-02'] }]
let client: QueryClient

function Cards({ count, supplied }: { count: number; supplied: boolean }) {
    const viewport = useChatChartViewport()
    return (
        <ScrollView testID="chart-viewport" onLayout={viewport.onLayout} onScroll={viewport.onScroll}>
            <ChatChartRow rowKey="long-message" index={0}>
                {Array.from({ length: count }, (_, index) => `event-${index}`).map((event) => (
                    <ChatVisualization
                        key={event}
                        title={event.replace('event-', 'Chart ')}
                        query={{ kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event }] }}
                        result={supplied ? result : undefined}
                    />
                ))}
            </ChatChartRow>
        </ScrollView>
    )
}

function view(count: number, supplied: boolean) {
    const screen = render(
        <QueryClientProvider client={client}>
            <ChatChartResources>
                <Cards count={count} supplied={supplied} />
            </ChatChartResources>
        </QueryClientProvider>
    )
    const cards = screen.getAllByTestId('chat-visualization')
    cards.forEach((card) => {
        fireEvent(card, 'layout', { nativeEvent: { layout: { y: 0, height: 200 } } })
    })
    const row = screen.getByTestId('chart-viewport').findByProps({ collapsable: false })
    fireEvent(row, 'layout', { nativeEvent: { layout: { y: 0, height: count * 240 } } })
    return screen
}

function scroll(screen: ReturnType<typeof render>, offset: number, height: number): void {
    fireEvent(screen.getByTestId('chart-viewport'), 'scroll', {
        nativeEvent: { contentOffset: { y: offset }, layoutMeasurement: { height } },
    })
}

beforeEach(() => {
    jest.clearAllMocks()
    viewsQueue.reset()
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
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
