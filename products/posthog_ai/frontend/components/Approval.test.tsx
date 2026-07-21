import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useActions, useValues } from 'kea'

import type { PermissionRequestRecord, ToolInvocation } from '../types/streamTypes'
import { PermissionInput } from './PermissionInput'

jest.mock('kea', () => ({
    ...jest.requireActual('kea'),
    useActions: jest.fn(),
    useValues: jest.fn(),
}))

jest.mock('use-resize-observer', () => () => ({
    height: 160,
    ref: { current: null },
}))

jest.mock('../logics/runStreamLogic', () => ({
    // Keyed logic — the component binds it with `runStreamLogic({ streamKey })`.
    runStreamLogic: jest.fn(() => ({ __mock: 'runStreamLogicInstance' })),
}))

jest.mock('../messages/MarkdownMessage', () => ({
    MarkdownMessage: ({ content }: { content: string }) => <div data-attr="markdown">{content}</div>,
}))

jest.mock('lib/components/CodeSnippet', () => ({
    CodeSnippet: ({ children }: { children: string }) => <pre data-attr="code-snippet">{children}</pre>,
    Language: { JSON: 'json', Text: 'text' },
}))

// Monaco can't render in jsdom — stand it in for a marker that echoes the diff props we care about.
jest.mock('lib/components/MonacoDiffEditor', () => ({
    __esModule: true,
    default: ({ original, modified }: { original?: string; modified?: string }) => (
        <div data-attr="monaco-diff" data-original={original} data-modified={modified} />
    ),
}))

jest.mock('react-intersection-observer', () => ({
    useInView: () => ({ ref: () => {}, inView: true }),
}))

const rawToolCall: ToolInvocation = {
    toolCallId: 'tc-1',
    rawServerName: 'posthog',
    rawToolName: 'exec',
    input: { command: 'call insight-create {"name":"Signups"}' },
    status: 'pending',
    contentBlocks: [],
}

function makeRequest(overrides: Partial<PermissionRequestRecord> = {}): PermissionRequestRecord {
    return {
        requestId: 'req-1',
        toolCallId: 'tc-1',
        toolName: 'mcp__posthog__exec',
        title: 'Create insight',
        description: 'The agent wants to create an insight.',
        options: [
            { optionId: 'opt-allow', name: 'Approve', kind: 'allow_once' },
            { optionId: 'opt-reject', name: 'Decline', kind: 'reject' },
        ],
        rawToolCall,
        ...overrides,
    }
}

describe('Sandbox approval input area', () => {
    const respondToPermission = jest.fn()
    const cancelRun = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()
        window.localStorage.removeItem('posthog-ai.lastPlanApprovalMode')
        ;(useActions as jest.Mock).mockReturnValue({ respondToPermission, cancelRun })
        ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: false })
    })

    afterEach(() => {
        cleanup()
    })

    describe('PermissionInput', () => {
        it('renders the one-voice card: headline sentence, tool identity, option rows', () => {
            render(<PermissionInput streamKey="conv-1" request={makeRequest()} />)

            expect(screen.getByText('The agent wants to create an insight.')).toBeInTheDocument()
            expect(screen.getByText('posthog - insight-create (MCP)')).toBeInTheDocument()
            expect(screen.getByText('Approve')).toBeInTheDocument()
            expect(screen.getByText('Decline')).toBeInTheDocument()
            // The redundant category rows are gone — the headline sentence carries the ask.
            expect(screen.queryByText('Approval required')).not.toBeInTheDocument()
        })

        it('states the tool identity exactly once when the request has a title but no description', () => {
            render(<PermissionInput streamKey="conv-1" request={makeRequest({ description: undefined })} />)

            // getByText throws on multiple matches, so this also asserts the identity isn't duplicated
            // between the headline and the evidence label.
            expect(screen.getByText('posthog - insight-create (MCP)')).toBeInTheDocument()
            // The raw adapter title must not ride in as a second statement of the same identity.
            expect(screen.queryByText('Create insight')).not.toBeInTheDocument()
        })

        it('renders the unwrapped PostHog exec payload like PostHog Desktop', () => {
            render(
                <PermissionInput
                    streamKey="conv-1"
                    request={makeRequest({
                        rawToolCall: {
                            ...rawToolCall,
                            input: { command: 'call execute-sql {"query":"select 1"}' },
                        },
                    })}
                />
            )

            expect(screen.getByText('posthog - execute-sql (MCP)')).toBeInTheDocument()
            expect(
                screen.getByText((_content, element) => element?.getAttribute('data-attr') === 'code-snippet')
                    .textContent
            ).toEqual('{\n  "query": "select 1"\n}')
        })

        it('posts the chosen optionId on click', () => {
            render(<PermissionInput streamKey="conv-1" request={makeRequest()} />)

            fireEvent.click(screen.getByText('Approve'))

            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'req-1',
                optionId: 'opt-allow',
            })
        })

        it('guards against double-submit while the reply POST is in flight', () => {
            // The logic's respondingToPermission flag drives the loading state — it flips
            // synchronously on dispatch and resets on success and on failure alike.
            ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: true })
            render(<PermissionInput streamKey="conv-1" request={makeRequest()} />)

            // Loading message replaces the option list, so nothing can be clicked.
            expect(screen.getByText('Sending response…')).toBeInTheDocument()
            expect(screen.queryByText('Approve')).not.toBeInTheDocument()
            expect(screen.queryByText('Decline')).not.toBeInTheDocument()
            expect(respondToPermission).not.toHaveBeenCalled()
        })

        it('sends feedback text through the reject_with_feedback option, ignoring an empty submit', () => {
            render(
                <PermissionInput
                    streamKey="conv-1"
                    request={makeRequest({
                        options: [
                            { optionId: 'opt-allow', name: 'Approve', kind: 'allow_once' },
                            { optionId: 'opt-feedback', name: 'Decline with feedback', kind: 'reject_with_feedback' },
                        ],
                    })}
                />
            )

            fireEvent.click(screen.getByText('Decline with feedback'))
            const input = screen.getByPlaceholderText('Tell the agent what to do differently')

            // The legacy feedback-only decline needs text — an empty Enter is a no-op.
            fireEvent.keyDown(input, { key: 'Enter' })
            expect(respondToPermission).not.toHaveBeenCalled()

            fireEvent.change(input, { target: { value: 'Use a funnel instead' } })
            fireEvent.keyDown(input, { key: 'Enter' })

            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'req-1',
                optionId: 'opt-feedback',
                customInput: 'Use a funnel instead',
            })
        })

        it('opens the note for a reject_once decline that supports feedback, declining plain on empty submit', () => {
            const request = makeRequest({
                options: [
                    { optionId: 'opt-allow', name: 'Yes', kind: 'allow_once' },
                    {
                        optionId: 'opt-reject',
                        name: 'Type here to tell the agent what to do differently',
                        kind: 'reject_once',
                        customInput: true,
                    },
                ],
            })
            render(<PermissionInput streamKey="conv-1" request={request} />)

            // The interaction-describing wire name becomes a named choice; the note is opened, not sent.
            fireEvent.click(screen.getByText('Do it differently…'))
            const input = screen.getByPlaceholderText('Tell the agent what to do differently')
            expect(respondToPermission).not.toHaveBeenCalled()

            // An empty submit is the plain one-click decline.
            fireEvent.keyDown(input, { key: 'Enter' })
            expect(respondToPermission).toHaveBeenCalledWith({ requestId: 'req-1', optionId: 'opt-reject' })

            // A typed note rides along as feedback.
            respondToPermission.mockClear()
            fireEvent.change(input, { target: { value: 'Try a different query' } })
            fireEvent.keyDown(input, { key: 'Enter' })
            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'req-1',
                optionId: 'opt-reject',
                customInput: 'Try a different query',
            })
        })

        it('activates rows with digit shortcuts but never while typing a note', () => {
            const request = makeRequest({
                options: [
                    { optionId: 'opt-allow', name: 'Approve', kind: 'allow_once' },
                    { optionId: 'opt-reject', name: 'No', kind: 'reject_once', customInput: true },
                ],
            })
            render(<PermissionInput streamKey="conv-1" request={request} />)

            // '2' opens the feedback note; digits typed inside it must not activate rows.
            fireEvent.keyDown(document.body, { key: '2' })
            const input = screen.getByPlaceholderText('Tell the agent what to do differently')
            fireEvent.keyDown(input, { key: '1' })
            expect(respondToPermission).not.toHaveBeenCalled()

            // Escape leaves the note; '1' back on the body approves.
            fireEvent.keyDown(input, { key: 'Escape' })
            fireEvent.keyDown(document.body, { key: '1' })
            expect(respondToPermission).toHaveBeenCalledWith({ requestId: 'req-1', optionId: 'opt-allow' })
        })

        it('caps a long payload behind a Show all expander', () => {
            const bigArgs = JSON.stringify({ query: 'select 1', cols: Array.from({ length: 20 }, (_, i) => `c${i}`) })
            render(
                <PermissionInput
                    streamKey="conv-1"
                    request={makeRequest({
                        rawToolCall: { ...rawToolCall, input: { command: `call execute-sql ${bigArgs}` } },
                    })}
                />
            )

            const snippet = (): HTMLElement =>
                screen.getByText((_content, element) => element?.getAttribute('data-attr') === 'code-snippet')
            expect(snippet().textContent).toContain('"c0"')
            expect(snippet().textContent).not.toContain('"c19"')

            fireEvent.click(screen.getByText(/^Show all \d+ lines$/))
            expect(snippet().textContent).toContain('"c19"')
        })

        it('renders diff evidence instead of the raw payload when the tool call carries a diff', () => {
            render(
                <PermissionInput
                    streamKey="conv-1"
                    request={makeRequest({
                        rawToolCall: {
                            ...rawToolCall,
                            contentBlocks: [
                                { type: 'diff', path: 'source.hog', oldText: 'let a := 1', newText: 'let a := 2' },
                            ],
                        },
                    })}
                />
            )

            const diff = document.querySelector('[data-attr="monaco-diff"]')
            expect(diff).not.toBeNull()
            expect(diff?.getAttribute('data-original')).toBe('let a := 1')
            expect(diff?.getAttribute('data-modified')).toBe('let a := 2')
            expect(screen.getByText('+1')).toBeInTheDocument()
            expect(screen.getByText('-1')).toBeInTheDocument()
            expect(
                screen.queryByText((_content, element) => element?.getAttribute('data-attr') === 'code-snippet')
            ).not.toBeInTheDocument()
        })

        // Plan approval keeps only the product's Auto and Full auto continuation modes. Plan, the retired
        // acceptEdits mode, and the agent server's raw default mode are deliberately ignored even if the
        // wire offers them.
        const planWireOptions = [
            { optionId: 'bypassPermissions', name: 'Yes, and bypass permissions', kind: 'allow_always' },
            { optionId: 'auto', name: 'Yes, and use "auto" mode', kind: 'allow_always' },
            { optionId: 'acceptEdits', name: 'Yes, and auto-accept edits', kind: 'allow_always' },
            { optionId: 'plan', name: 'Stay in plan mode', kind: 'allow_always' },
            { optionId: 'default', name: 'Yes, and manually approve edits', kind: 'allow_once' },
            {
                optionId: 'reject_with_feedback',
                name: 'No, and tell the agent what to do differently',
                kind: 'reject_once',
                customInput: true,
            },
        ]

        function makePlanRequest(overrides: Partial<PermissionRequestRecord> = {}): PermissionRequestRecord {
            return makeRequest({
                toolName: '',
                title: 'Ready to code?',
                description: undefined,
                options: planWireOptions,
                rawToolCall: {
                    ...rawToolCall,
                    kind: 'switch_mode',
                    title: 'Ready to code?',
                    input: { plan: '# The plan', planFilePath: '/tmp/plan.md', toolName: 'ExitPlanMode' },
                },
                ...overrides,
            })
        }

        it.each([
            ['the request is for ExitPlanMode', makePlanRequest({ toolName: 'ExitPlanMode', rawToolCall })],
            ['the tool call is tagged as a plan', makePlanRequest({ rawToolCall: { ...rawToolCall, kind: 'plan' } })],
            // The real agent-server wire shape: no top-level tool name, `kind: 'switch_mode'`, and the
            // tool name embedded in the input payload alongside the plan.
            ['the tool input carries the ExitPlanMode tool name', makePlanRequest()],
        ])('shows the plan-approval selector when %s', (_case, request) => {
            render(<PermissionInput streamKey="conv-1" request={request} />)

            expect(screen.getByText('Implementation Plan')).toBeInTheDocument()
            expect(screen.getByText('Approve this plan to proceed?')).toBeInTheDocument()
        })

        it('keeps the supported plan modes and approves with the default Auto as the auto wire option', () => {
            render(<PermissionInput streamKey="conv-1" request={makePlanRequest()} />)

            expect(screen.getByText('Auto')).toBeInTheDocument()
            fireEvent.click(screen.getByText('Approve and proceed'))

            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'req-1',
                optionId: 'auto',
            })
        })

        it('pre-selects the remembered last-approved mode over Auto', () => {
            window.localStorage.setItem('posthog-ai.lastPlanApprovalMode', 'bypassPermissions')
            render(<PermissionInput streamKey="conv-1" request={makePlanRequest()} />)

            fireEvent.click(screen.getByText('Approve and proceed'))

            expect(respondToPermission).toHaveBeenCalledWith({ requestId: 'req-1', optionId: 'bypassPermissions' })
        })

        it('falls back to Auto when the remembered mode is retired', () => {
            window.localStorage.setItem('posthog-ai.lastPlanApprovalMode', 'acceptEdits')
            render(<PermissionInput streamKey="conv-1" request={makePlanRequest()} />)

            fireEvent.click(screen.getByText('Approve and proceed'))

            expect(respondToPermission).toHaveBeenCalledWith({ requestId: 'req-1', optionId: 'auto' })
        })

        it('opens the mode picker with only Auto and Full auto', () => {
            render(<PermissionInput streamKey="conv-1" request={makePlanRequest()} />)

            fireEvent.click(screen.getByLabelText('Mode'))

            expect(screen.getByText('Full auto')).toBeInTheDocument()
            expect(screen.queryByText('Accept edits')).not.toBeInTheDocument()
            expect(screen.queryByText('Default')).not.toBeInTheDocument()
            expect(screen.queryByText('Plan')).not.toBeInTheDocument()
            expect(screen.queryByText('Bypass permissions')).not.toBeInTheDocument()
        })

        it('sends plan rejection feedback through the reject row, ignoring an empty submit', () => {
            render(<PermissionInput streamKey="conv-1" request={makePlanRequest()} />)

            // Select the reject row, then submit with Enter — empty feedback is a no-op.
            fireEvent.click(screen.getByText('2.'))
            const input = screen.getByPlaceholderText('Type here to tell the agent what to do differently')
            fireEvent.keyDown(input, { key: 'Enter' })
            expect(respondToPermission).not.toHaveBeenCalled()

            fireEvent.change(input, { target: { value: 'Use a different approach' } })
            fireEvent.keyDown(input, { key: 'Enter' })

            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'req-1',
                optionId: 'reject_with_feedback',
                customInput: 'Use a different approach',
            })
        })

        it('handles the digit and Escape shortcuts without the selector being focused', () => {
            render(<PermissionInput streamKey="conv-1" request={makePlanRequest()} />)

            // Shortcuts are window-level — fired on the page body, not on the selector.
            fireEvent.keyDown(document.body, { key: 'Escape' })
            expect(cancelRun).toHaveBeenCalled()
            expect(respondToPermission).not.toHaveBeenCalled()

            fireEvent.keyDown(document.body, { key: '1' })
            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'req-1',
                optionId: 'auto',
            })
        })

        it('leaves keys alone when focus sits on an element outside the card', () => {
            render(<PermissionInput streamKey="conv-1" request={makePlanRequest()} />)

            // Focus parked on unrelated page chrome (a nav button) — Enter must keep activating that
            // element and Tab must keep moving focus, never approve the plan or cycle its mode.
            const outsideButton = document.createElement('button')
            document.body.appendChild(outsideButton)
            outsideButton.focus()

            const tabNotPrevented = fireEvent.keyDown(outsideButton, { key: 'Tab' })
            fireEvent.keyDown(outsideButton, { key: 'Enter' })
            fireEvent.keyDown(outsideButton, { key: '1' })
            outsideButton.remove()

            // Tab was not prevented — the browser's native focus traversal still happens.
            expect(tabNotPrevented).toBe(true)
            expect(respondToPermission).not.toHaveBeenCalled()
            expect(cancelRun).not.toHaveBeenCalled()
        })

        it('blocks plan approval while the response POST is in flight', () => {
            ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: true })
            render(<PermissionInput streamKey="conv-1" request={makePlanRequest()} />)

            fireEvent.click(screen.getByText('Approve and proceed'))

            expect(respondToPermission).not.toHaveBeenCalled()
        })

        it('keeps the approve options on the fallback card when no plan mode id is recognized', () => {
            // Version-skew shape: a plan request whose approve ids all predate/postdate the known mode
            // enum. The fallback card must keep the `allow_always` approve options, not go decline-only.
            render(
                <PermissionInput
                    streamKey="conv-1"
                    request={makePlanRequest({
                        options: [
                            { optionId: 'future-mode', name: 'Yes, use future mode', kind: 'allow_always' },
                            {
                                optionId: 'reject_with_feedback',
                                name: 'No, tell the agent what to do differently',
                                kind: 'reject_once',
                            },
                        ],
                    })}
                />
            )

            expect(screen.getByText('Yes, use future mode')).toBeInTheDocument()
            expect(screen.getByText('No, tell the agent what to do differently')).toBeInTheDocument()
        })

        it('does not show plan copy just because the title mentions a plan', () => {
            render(
                <PermissionInput streamKey="conv-1" request={makeRequest({ title: 'Create a data retention plan' })} />
            )

            expect(screen.queryByText('Implementation Plan')).not.toBeInTheDocument()
            expect(screen.getByText('Approve')).toBeInTheDocument()
        })

        it('falls back to showing every option when filtering would leave none', () => {
            render(
                <PermissionInput
                    streamKey="conv-1"
                    request={makeRequest({
                        options: [{ optionId: 'opt-always', name: '', kind: 'allow_always' }],
                    })}
                />
            )

            expect(screen.getByText('Approve always')).toBeInTheDocument()
        })
    })
})
