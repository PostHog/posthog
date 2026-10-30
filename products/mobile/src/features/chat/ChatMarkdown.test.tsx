import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, waitFor } from '@testing-library/react-native'
import { Linking, useColorScheme } from 'react-native'
import { getInsightSummary } from '@/api/insights'
import { darkColors } from '@/ui/theme'
import { ChatMarkdown } from './ChatMarkdown'
import { MermaidDiagram } from './MermaidDiagram'

jest.mock('@/auth/useProjectScope', () => ({ useProjectScope: () => ({ host: 'https://example.com', projectId: 7 }) }))
jest.mock('@/api/insights', () => ({ getInsightSummary: jest.fn() }))
jest.mock('./MermaidDiagram', () => ({ MermaidDiagram: jest.fn(() => null) }))
const summary = getInsightSummary as jest.MockedFunction<typeof getInsightSummary>
let client: QueryClient
function view(text: string): ReturnType<typeof render> {
    return render(
        <QueryClientProvider client={client}>
            <ChatMarkdown text={text} />
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
        client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: Infinity } } })
    })
    afterEach(() => {
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
    test('shows loading, name and description without executing SQL', async () => {
        let resolve: (value: { name: string; description: string }) => void = () => undefined
        summary.mockReturnValue(
            new Promise((done) => {
                resolve = done
            })
        )
        const screen = view('<insight id="abc" display="block"/>')
        expect(screen.getByText('Loading insight…')).toBeTruthy()
        resolve({ name: 'Count', description: 'Visits per day' })
        await waitFor(() => expect(screen.getByText('Visits per day')).toBeTruthy())
        expect(summary).toHaveBeenCalledWith('abc', expect.any(AbortSignal))
    })
    test('shows unavailable for a missing insight with a supplied title', async () => {
        summary.mockResolvedValue(null)
        const screen = view('<insight id="missing" title="Visits" display="block"/>')
        await waitFor(() => expect(screen.getByText('Insight unavailable')).toBeTruthy())
    })
    test('keeps errors visible with a supplied title', async () => {
        summary.mockRejectedValue(new Error('unavailable'))
        const screen = view('<insight id="abc" title="Visits" display="block"/>')
        await waitFor(() => expect(screen.getByText('Could not load insight')).toBeTruthy())
        expect(screen.getByText('Visits')).toBeTruthy()
    })
    test('expands SQL without opening its editor', () => {
        const open = jest.spyOn(Linking, 'openURL').mockResolvedValue(undefined)
        const screen = view('<hogql display="block">SELECT 1\nUNION ALL\nSELECT 2\nORDER BY 1</hogql>')
        fireEvent.press(screen.getByText('Show all'))
        expect(screen.getByText('Show less')).toBeTruthy()
        expect(open).not.toHaveBeenCalled()
        fireEvent.press(screen.getByText('SQL query'))
        expect(open).toHaveBeenCalledWith(
            'https://example.com/project/7/sql?open_query=SELECT%201%0AUNION%20ALL%0ASELECT%202%0AORDER%20BY%201'
        )
    })
})
