import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import type { ToolCallMessage } from '../../types/toolTypes'
import { EditDiffRenderer } from './EditDiffRenderer'

// Monaco can't render in jsdom — stand it in for a marker that echoes the diff props we care about.
jest.mock('lib/components/MonacoDiffEditor', () => ({
    __esModule: true,
    default: ({
        original,
        modified,
        language,
        theme,
    }: {
        original?: string
        modified?: string
        language?: string
        theme?: string
    }) => (
        <div
            data-attr="monaco-diff"
            data-original={original}
            data-modified={modified}
            data-language={language}
            data-theme={theme}
        />
    ),
}))

// A newly created file renders the single-pane read view, not a diff — stand it in for a marker that
// echoes the content + path so jsdom never instantiates real Monaco (and never pulls monaco-editor).
jest.mock('./ReadFileContent', () => ({
    __esModule: true,
    ReadFileContent: ({ text, path }: { text: string; path?: string }) => (
        <div data-attr="read-file" data-text={text} data-path={path} />
    ),
}))

// Force the lazy-mount gate open so the editor instantiates.
jest.mock('react-intersection-observer', () => ({
    useInView: () => ({ ref: () => {}, inView: true }),
}))

// Drive the app theme without mounting themeLogic (and its scene/user deps). The arrow reads
// `mockDarkMode` lazily at render time, so flipping it per test works.
let mockDarkMode = false
jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useValues: () => ({ isDarkModeOn: mockDarkMode }),
}))

function makeMessage(overrides: Partial<ToolCallMessage> = {}): ToolCallMessage {
    return {
        id: 'tc-1',
        resolvedKey: 'Edit',
        rawServerName: 'posthog',
        rawToolName: 'Edit',
        rawInput: {},
        content: [],
        status: 'completed',
        ...overrides,
    }
}

// The diff lives in the Activity's collapsible body, which auto-collapses once the call completes —
// expand it so the editor + stats render.
function renderExpanded(message: ToolCallMessage): void {
    render(<EditDiffRenderer message={message} displayName="Edit" isLastInGroup />)
    fireEvent.click(screen.getByRole('button'))
}

describe('EditDiffRenderer', () => {
    afterEach(() => {
        cleanup()
        mockDarkMode = false
    })

    it('renders an inline diff with +/- stats for an Edit with a diff block', () => {
        renderExpanded(
            makeMessage({
                title: 'Edit `foo.ts`',
                content: [{ type: 'diff', path: 'foo.ts', oldText: 'a\nb', newText: 'a\nb\nc' }],
            })
        )

        const editor = screen.getByTestId('monaco-diff')
        expect(editor).toBeInTheDocument()
        expect(editor).toHaveAttribute('data-original', 'a\nb')
        expect(editor).toHaveAttribute('data-modified', 'a\nb\nc')
        expect(editor).toHaveAttribute('data-language', 'typescript')
        expect(editor).toHaveAttribute('data-theme', 'vs')
        expect(screen.getByText('foo.ts')).toBeInTheDocument()
        expect(screen.getByText('+1')).toBeInTheDocument()
        expect(screen.getByText('-0')).toBeInTheDocument()
    })

    it('reads "Edited a file" in the header', () => {
        render(
            <EditDiffRenderer
                message={makeMessage({ content: [{ type: 'diff', path: 'foo.ts', oldText: 'a', newText: 'b' }] })}
                displayName="Edit"
                isLastInGroup
            />
        )
        expect(screen.getByText('Edited a file')).toBeInTheDocument()
    })

    it('renders one editor per diff block for a MultiEdit', () => {
        renderExpanded(
            makeMessage({
                resolvedKey: 'MultiEdit',
                content: [
                    { type: 'diff', path: 'foo.ts', oldText: 'a', newText: 'b' },
                    { type: 'content', content: { type: 'diff', path: 'foo.ts', oldText: 'b', newText: 'c' } },
                ],
            })
        )

        expect(screen.getAllByTestId('monaco-diff')).toHaveLength(2)
    })

    it('renders a single-pane read view (not a diff) with all-added stats for a new file (Write)', () => {
        const message = makeMessage({
            resolvedKey: 'Write',
            content: [{ type: 'diff', path: 'new.py', oldText: null, newText: 'print(1)\nprint(2)' }],
        })
        render(<EditDiffRenderer message={message} displayName="Edit" isLastInGroup />)
        expect(screen.getByText('Created a file')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button'))
        expect(screen.queryByTestId('monaco-diff')).not.toBeInTheDocument()
        const readView = screen.getByTestId('read-file')
        expect(readView).toHaveAttribute('data-text', 'print(1)\nprint(2)')
        expect(readView).toHaveAttribute('data-path', 'new.py')
        expect(screen.getByText('new.py')).toBeInTheDocument()
        expect(screen.getByText('+2')).toBeInTheDocument()
    })

    it('resolves filename and language from rawInput.file_path when the diff block has no path', () => {
        renderExpanded(
            makeMessage({
                content: [{ type: 'diff', oldText: 'a', newText: 'b' }],
                rawInput: { file_path: 'main.go' },
            })
        )

        expect(screen.getByText('main.go')).toBeInTheDocument()
        expect(screen.getByTestId('monaco-diff')).toHaveAttribute('data-language', 'go')
    })

    it('falls back to the generic tool card (no editor) when there is no diff block', () => {
        // A built-in Edit carries its name in `claudeToolName` with an empty wire `toolName`.
        const message = makeMessage({
            title: 'Edit `foo.ts`',
            claudeToolName: 'Edit',
            rawToolName: '',
            content: [{ type: 'text', text: 'no diff yet' }],
        })
        render(<EditDiffRenderer message={message} displayName="Edit" isLastInGroup />)

        expect(screen.queryByTestId('monaco-diff')).not.toBeInTheDocument()
        // The generic card still renders the rich tool title as its header.
        expect(screen.getByText('Edit `foo.ts`')).toBeInTheDocument()
    })

    it('uses the dark Monaco theme when the app is in dark mode', () => {
        mockDarkMode = true
        renderExpanded(makeMessage({ content: [{ type: 'diff', path: 'foo.ts', oldText: 'a', newText: 'b' }] }))

        expect(screen.getByTestId('monaco-diff')).toHaveAttribute('data-theme', 'vs-dark')
    })
})
