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

    beforeEach(() => {
        jest.clearAllMocks()
        ;(useActions as jest.Mock).mockReturnValue({ respondToPermission })
        ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: false, currentMode: null })
    })

    afterEach(() => {
        cleanup()
    })

    describe('PermissionInput', () => {
        it('renders the approval prompt with the same two permission options', () => {
            render(<PermissionInput streamKey="conv-1" request={makeRequest()} />)

            expect(screen.getByText('Approval required')).toBeInTheDocument()
            expect(screen.getByText('posthog - insight-create (MCP)')).toBeInTheDocument()
            expect(screen.getByText('Approve')).toBeInTheDocument()
            expect(screen.getByText('Decline')).toBeInTheDocument()
            expect(screen.queryByText("Explain what you'd like instead.")).not.toBeInTheDocument()
        })

        it('renders the unwrapped PostHog exec payload like PostHog Code', () => {
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

        it('sends feedback text through the reject_with_feedback option when it is the decline path', () => {
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

            fireEvent.click(screen.getByText("Explain what you'd like instead."))
            const input = screen.getByPlaceholderText('Type your answer...')
            fireEvent.change(input, { target: { value: 'Use a funnel instead' } })
            fireEvent.click(screen.getByText('Send'))

            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'req-1',
                optionId: 'opt-feedback',
                customInput: 'Use a funnel instead',
            })
        })

        it('renders reject_once as a one-click decline with no feedback toggle', () => {
            const request = makeRequest({
                options: [
                    { optionId: 'opt-allow', name: 'Yes', kind: 'allow_once' },
                    { optionId: 'opt-reject', name: 'No', kind: 'reject_once', customInput: true },
                ],
            })
            render(<PermissionInput streamKey="conv-1" request={request} />)

            // No optional-feedback affordance — the decline is a plain one-click button.
            expect(screen.queryByText('Add feedback…')).not.toBeInTheDocument()
            fireEvent.click(screen.getByText('No'))
            expect(respondToPermission).toHaveBeenCalledWith({
                requestId: 'req-1',
                optionId: 'opt-reject',
            })
        })

        it.each([
            [
                'the agent is in plan mode',
                (): void => {
                    ;(useValues as jest.Mock).mockReturnValue({ respondingToPermission: false, currentMode: 'plan' })
                },
                makeRequest(),
            ],
            [
                'the tool call is tagged as a plan',
                (): void => {},
                makeRequest({ rawToolCall: { ...rawToolCall, kind: 'plan' } }),
            ],
        ])('shows plan copy when %s', (_case, arrange, request) => {
            arrange()
            render(<PermissionInput streamKey="conv-1" request={request} />)

            expect(screen.getByText('Approve this plan?')).toBeInTheDocument()
        })

        it('does not show plan copy just because the title mentions a plan', () => {
            render(
                <PermissionInput streamKey="conv-1" request={makeRequest({ title: 'Create a data retention plan' })} />
            )

            expect(screen.getByText('Approval required')).toBeInTheDocument()
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
