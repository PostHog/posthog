import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, waitFor } from '@testing-library/react-native'
import { Linking } from 'react-native'
import { type InsightApi, readInsight } from '@/api/insights'
import { runQuery } from '@/api/query'
import { viewsQueue } from '@/features/views/refreshQueue'
import { ChatVisualization, type ChatVisualizationProps } from './ChatVisualization'
import { classicVisualizationItems } from './classicVisualizations'

jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => ({ host: 'https://example.com', projectId: 42 }) }))
jest.mock('@/api/insights', () => ({ readInsight: jest.fn() }))
jest.mock('@/api/query', () => ({ ...jest.requireActual('@/api/query'), runQuery: jest.fn() }))
jest.mock('@/ui/chart/MetricChartCanvas', () => {
    const { createElement } = jest.requireActual('react')
    const { View } = jest.requireActual('react-native')
    return {
        MetricChartCanvas: ({ label, barLayout }: { label: string; barLayout: string }) =>
            createElement(View, { accessibilityLabel: `${label} chart`, accessibilityValue: { text: barLayout } }),
    }
})

const trendQuery = { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: '$pageview' }] }
const trendResult = [{ data: [12, 15], days: ['2026-10-01', '2026-10-02'] }]
let client: QueryClient

function view(props: ChatVisualizationProps): ReturnType<typeof render> {
    return render(
        <QueryClientProvider client={client}>
            <ChatVisualization {...props} />
        </QueryClientProvider>
    )
}

beforeEach(() => {
    jest.clearAllMocks()
    client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
})
afterEach(() => {
    viewsQueue.reset()
    client.clear()
    jest.restoreAllMocks()
})

test.each([
    {
        kind: 'TrendsQuery',
        series: [
            { kind: 'EventsNode', event: '$pageview' },
            { kind: 'EventsNode', event: 'signup' },
        ],
        trendsFilter: { display: 'ActionsBar' },
    },
    {
        kind: 'DataVisualizationNode',
        source: { kind: 'HogQLQuery', query: 'SELECT day, first, second FROM example_daily' },
        display: 'ActionsStackedBar',
        chartSettings: { xAxis: { column: 'day' }, yAxis: [{ column: 'first' }, { column: 'second' }] },
    },
])('preserves the saved stacked bar layout: %j', (query) => {
    const result =
        query.kind === 'TrendsQuery'
            ? [...trendResult, { data: [3, 8], days: ['2026-10-01', '2026-10-02'] }]
            : {
                  columns: ['day', 'first', 'second'],
                  types: [
                      ['day', 'Date'],
                      ['first', 'Int64'],
                      ['second', 'Int64'],
                  ],
                  results: [
                      ['2026-10-01', 12, 3],
                      ['2026-10-02', 15, 8],
                  ],
              }
    const screen = view({ query, title: 'Stacked visits', result })
    expect(screen.getByLabelText('Stacked visits chart')).toHaveAccessibilityValue({ text: 'stacked' })
})

test.each([false, true])(
    'computes a saved insight cache miss only when the chart is supported: %s',
    async (supported) => {
        const modes: string[] = []
        jest.mocked(readInsight).mockImplementation(async (_target, { refresh }) => {
            modes.push(refresh)
            return {
                id: 9,
                short_id: 'saved',
                name: 'Saved visits',
                derived_name: null,
                query: supported ? { kind: 'InsightVizNode', source: trendQuery } : { kind: 'PathsQuery' },
                result: refresh === 'force_cache' ? null : trendResult,
                last_refresh: refresh === 'force_cache' ? null : '2026-10-03T00:00:00Z',
                cache_target_age: null,
                next_allowed_client_refresh: null,
            } as InsightApi
        })
        const screen = view({ shortId: 'saved' })
        if (supported) await waitFor(() => expect(screen.getByLabelText('Saved visits chart')).toBeTruthy())
        else await waitFor(() => expect(screen.getByText('Open this chart on the web to view it.')).toBeTruthy())
        expect(modes).toEqual(supported ? ['force_cache', 'blocking'] : ['force_cache'])
    }
)

test('retains historical visualization identity across unrelated streaming updates', () => {
    const message = { type: 'ai/viz', answer: trendQuery, result: trendResult }
    const original = classicVisualizationItems(message, 'chart', 'https://example.com/project/42')
    expect(classicVisualizationItems(message, 'chart', 'https://example.com/project/42')).toBe(original)
    const changed = classicVisualizationItems(message, 'chart', 'https://example.com/project/43')
    expect(changed[0]).toMatchObject({ webUrl: expect.stringContaining('/project/43/') })
})

test.each([trendResult, { results: trendResult }, { result: trendResult }])(
    'draws a supplied trends result without a second query: %j',
    (result) => {
        const screen = view({ query: trendQuery, title: 'Visits', result })
        expect(screen.getByLabelText('Visits chart')).toBeTruthy()
        expect(runQuery).not.toHaveBeenCalled()
    }
)

test.each([undefined, null, {}, { results: 'invalid' }])(
    'fetches a generated query when inline results are absent: %j',
    async (result) => {
        jest.mocked(runQuery).mockResolvedValue({ results: trendResult })
        const screen = view({ query: trendQuery, title: 'Visits', result })
        await waitFor(() => expect(screen.getByLabelText('Visits chart')).toBeTruthy())
        expect(runQuery).toHaveBeenCalledWith(
            trendQuery,
            expect.objectContaining({ scope: { host: 'https://example.com', projectId: 42 } })
        )
    }
)

test('renders the proposed query and keeps a saved insight as its web destination', async () => {
    const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
    jest.mocked(runQuery).mockResolvedValue({
        columns: ['status'],
        types: [['status', 'String']],
        results: [['Proposed result']],
    })
    const screen = view({
        shortId: 'saved',
        query: { kind: 'HogQLQuery', query: "SELECT 'Proposed result' AS status" },
    })
    await waitFor(() => expect(screen.getByText('Proposed result')).toBeTruthy())
    expect(readInsight).not.toHaveBeenCalled()
    fireEvent.press(screen.getByText('Open insight'))
    expect(open).toHaveBeenCalledWith('https://example.com/project/42/insights/saved')
    jest.mocked(runQuery).mockResolvedValue({
        columns: ['status'],
        types: [['status', 'String']],
        results: [['Revised result']],
    })
    screen.rerender(
        <QueryClientProvider client={client}>
            <ChatVisualization
                shortId="saved"
                query={{ kind: 'HogQLQuery', query: "SELECT 'Revised result' AS status" }}
            />
        </QueryClientProvider>
    )
    await waitFor(() => expect(screen.getByText('Revised result')).toBeTruthy())
    expect(screen.queryByText('Proposed result')).toBeNull()
})

test('reads saved metadata when only a result and saved insight reference were supplied', async () => {
    jest.mocked(readInsight).mockResolvedValue({
        id: 9,
        short_id: 'saved',
        name: 'Saved visits',
        derived_name: null,
        query: { kind: 'InsightVizNode', source: trendQuery },
        result: trendResult,
        last_refresh: '2026-10-03T00:00:00Z',
        cache_target_age: null,
        next_allowed_client_refresh: null,
    })
    const screen = view({ shortId: 'saved', result: trendResult })
    await waitFor(() => expect(screen.getByLabelText('Saved visits chart')).toBeTruthy())
    expect(runQuery).not.toHaveBeenCalled()
})

test.each([[[42]], { results: [[42]] }, { results: [[42]], columns: [] }])(
    'fetches missing SQL column metadata before drawing a result: %j',
    async (result) => {
        jest.mocked(runQuery).mockResolvedValue({ columns: ['count'], types: [['count', 'Int64']], results: [[42]] })
        const screen = view({ query: { kind: 'HogQLQuery', query: 'SELECT 42 AS count' }, result })
        await waitFor(() => expect(screen.getByText('42')).toBeTruthy())
        expect(screen.getByText('count')).toBeTruthy()
    }
)

test('draws SQL result columns and rows, including a null cell', () => {
    const screen = view({
        query: { kind: 'HogQLQuery', query: 'SELECT browser, count() FROM events GROUP BY browser' },
        result: {
            columns: ['browser', 'count'],
            types: [
                ['browser', 'String'],
                ['count', 'Int64'],
            ],
            results: [
                ['Example browser', 23],
                [null, 5],
            ],
        },
    })
    expect(screen.getByText('Example browser')).toBeTruthy()
    expect(screen.getByText('23')).toBeTruthy()
    expect(runQuery).not.toHaveBeenCalled()
})

test('shows an empty range instead of a blank canvas', () => {
    const screen = view({ query: trendQuery, result: [] })
    expect(screen.getByText('No data')).toBeTruthy()
    expect(screen.queryByTestId('chat-visualization-chart')).toBeNull()
})

test('leaves unsupported chart kinds on the web without executing their query', () => {
    const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
    const query = { kind: 'PathsQuery', pathGroupings: [] }
    const screen = view({ query })
    expect(screen.getByText('Open this chart on the web to view it.')).toBeTruthy()
    fireEvent.press(screen.getByText('Open chart on web'))
    expect(runQuery).not.toHaveBeenCalled()
    expect(open).toHaveBeenCalledWith(expect.stringContaining('https://example.com/project/42/insights/new#q='))
})
