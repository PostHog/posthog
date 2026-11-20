import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, waitFor } from '@testing-library/react-native'
import { Linking, useColorScheme } from 'react-native'
import { ApiError } from '@/api/client'
import { type InsightApi, readInsight } from '@/api/insights'
import { runQuery } from '@/api/query'
import { viewsQueue } from '@/features/views/refreshQueue'
import { abortError } from '@/lib/abort'
import { darkColors } from '@/ui/theme'
import { ChatMarkdown } from './ChatMarkdown'
import { MermaidDiagram } from './MermaidDiagram'

jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => ({ host: 'https://example.com', projectId: 7 }) }))
jest.mock('@/api/insights', () => ({ readInsight: jest.fn() }))
jest.mock('@/api/query', () => ({ ...jest.requireActual('@/api/query'), runQuery: jest.fn() }))
jest.mock('./MermaidDiagram', () => ({ MermaidDiagram: jest.fn(() => null) }))
const read = jest.mocked(readInsight)
const query = jest.mocked(runQuery)
const trendQuery = { kind: 'TrendsQuery', series: [{ kind: 'EventsNode', event: '$pageview' }] }
function insight(overrides: Partial<InsightApi> = {}): InsightApi {
    return {
        id: 1,
        short_id: 'abc',
        name: 'Count',
        description: 'Visits per day',
        derived_name: null,
        query: { kind: 'InsightVizNode', source: trendQuery },
        result: [{ data: [12, 15], days: ['2026-10-01', '2026-10-02'] }],
        last_refresh: '2026-10-03T00:00:00Z',
        cache_target_age: null,
        next_allowed_client_refresh: null,
        ...overrides,
    }
}
let client: QueryClient
function view(text: string, projectUrl?: string): ReturnType<typeof render> {
    return render(
        <QueryClientProvider client={client}>
            <ChatMarkdown text={text} projectUrl={projectUrl} />
        </QueryClientProvider>
    )
}
describe('reply object rendering', () => {
    test('renders only closed Mermaid fences, including blockquotes', () => {
        const diagram = MermaidDiagram as jest.Mock
        view('```mermaid\nflowchart LR\nA-->B\n```')
        expect(diagram).toHaveBeenCalledWith(expect.objectContaining({ code: 'flowchart LR\nA-->B\n' }), undefined)
        diagram.mockClear()
        const screen = view('```mermaid\nflowchart LR\nA-->B')
        expect(diagram).not.toHaveBeenCalled()
        expect(screen.getByText('flowchart LR\nA-->B')).toBeTruthy()
        view('> ```mermaid\n> flowchart LR\n> A-->B\n> ```')
        expect(diagram).toHaveBeenCalled()
    })
    beforeEach(() => {
        jest.clearAllMocks()
        query.mockImplementation(
            (_query, options) =>
                new Promise((_resolve, reject) => {
                    options?.signal?.addEventListener('abort', () => reject(abortError()), { once: true })
                })
        )
        client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
    })
    afterEach(() => {
        viewsQueue.reset()
        client.clear()
        jest.restoreAllMocks()
        jest.mocked(useColorScheme).mockReturnValue('light')
    })
    test.each([
        ['reply', darkColors.ink],
        ['thought', darkColors.muted],
    ] as const)('draws %s code in the dark palette', (tone, color) => {
        jest.mocked(useColorScheme).mockReturnValue('dark')
        const screen = render(<ChatMarkdown text="Run `pnpm test` now" tone={tone} />)
        expect(screen.getByText('pnpm test')).toHaveStyle({ color })
    })
    test('opens an inline object in the current project', () => {
        const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
        const screen = view('See <insight id="abc">Count</insight>')
        fireEvent.press(screen.getByText('Count'))
        expect(open).toHaveBeenCalledWith('https://example.com/project/7/insights/abc')
    })
    test('opens explicit links and leaves bare URLs as text', () => {
        const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
        const screen = view(
            'Read https://example.com/bare or [the guide](https://example.com/guide) or <https://example.com/auto>'
        )
        expect(screen.queryByText('https://example.com/bare')).toBeNull()
        fireEvent.press(screen.getByText('the guide'))
        fireEvent.press(screen.getByText('https://example.com/auto'))
        expect(open.mock.calls).toEqual([['https://example.com/guide'], ['https://example.com/auto']])
    })
    test.each([
        ['/dashboard/123?tab=details#top', 'https://app.example.com/project/42/dashboard/123?tab=details#top'],
        ['/project/99/insights/abc', 'https://app.example.com/project/99/insights/abc'],
        ['/organization/settings', 'https://app.example.com/organization/settings'],
        ['https://external.example.com/guide', 'https://external.example.com/guide'],
    ])('opens %s in its intended project', (path, expected) => {
        const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
        const screen = view(`[Link](${path})`, 'https://app.example.com/project/42')
        fireEvent.press(screen.getByText('Link'))
        expect(open).toHaveBeenCalledWith(expected)
    })
    test.each([
        ['ordinary prose', 'plain words '],
        ['a repeated mailto: scheme', 'mailto:'],
        ['an opening angle bracket with no close', '<a '],
        ['an unknown tag', '<a>'],
        ['an object tag with no closing tag', '<insight>'],
        ['an object tag with no closing bracket', '<insight '],
    ])('parses %s with linear string copying', (_case, unit) => {
        const text = unit.repeat(Math.ceil(12_000 / unit.length))
        const slice = String.prototype.slice
        let copied = 0
        const spy = jest.spyOn(String.prototype, 'slice').mockImplementation(function (
            this: string,
            start?: number,
            end?: number
        ): string {
            const part = slice.call(this, start, end)
            copied += part.length
            return part
        })
        try {
            view(text)
        } finally {
            spy.mockRestore()
        }
        expect(copied).toBeLessThan(text.length * 50)
    })
    test('loads a saved insight and draws its native chart', async () => {
        let resolve: (value: InsightApi) => void = () => undefined
        read.mockReturnValue(
            new Promise((done) => {
                resolve = done
            })
        )
        const screen = view('<insight id="abc" display="block"/>')
        expect(screen.getByText('Loading insight…')).toBeTruthy()
        resolve(insight())
        await waitFor(() => expect(screen.getByText('Visits per day')).toBeTruthy())
        expect(screen.getByLabelText('Count chart')).toBeTruthy()
        expect(screen.getByText('Open insight')).toBeTruthy()
    })
    test('shows unavailable for a missing insight with a supplied title', async () => {
        read.mockRejectedValue(new ApiError(404, {}))
        const screen = view('<insight id="missing" title="Visits" display="block"/>')
        await waitFor(() => expect(screen.getByText('Insight unavailable')).toBeTruthy())
    })
    test('keeps errors visible with a supplied title', async () => {
        read.mockRejectedValue(new Error('unavailable'))
        const screen = view('<insight id="abc" title="Visits" display="block"/>')
        await waitFor(() =>
            expect(screen.getByText('Could not load chart. Open it on the web or try again.')).toBeTruthy()
        )
        expect(screen.getByText('Visits')).toBeTruthy()
        read.mockResolvedValue(insight())
        fireEvent.press(screen.getByText('Try again'))
        await waitFor(() => expect(screen.getByLabelText('Count chart')).toBeTruthy())
    })
    test('expands SQL without opening its editor', () => {
        const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
        const screen = view('<hogql display="block">SELECT 1\nUNION ALL\nSELECT 2\nORDER BY 1</hogql>')
        fireEvent.press(screen.getByText('Show all'))
        expect(screen.getByText('Show less')).toBeTruthy()
        expect(open).not.toHaveBeenCalled()
        fireEvent.press(screen.getByText('Open SQL editor'))
        expect(open).toHaveBeenCalledWith(
            'https://example.com/project/7/sql?open_query=SELECT%201%0AUNION%20ALL%0ASELECT%202%0AORDER%20BY%201'
        )
    })
})
