import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import { ReasoningAnswer } from '../messages/ReasoningAnswer'
import type { ToolInvocation } from '../types/streamTypes'
import type { ThreadActivityGroup as ActivityGroup } from '../utils/groupThreadActivity'
import { Activity } from './ActivityPrimitives'
import { ThreadActivityGroup } from './ThreadActivityGroup'
import { VirtualizedThread } from './VirtualizedThread'

jest.mock('../messages/MarkdownMessage', () => ({
    MarkdownMessage: ({ content }: { content: string }) => <div>{content}</div>,
}))

describe('ThreadActivityGroup', () => {
    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each([2, 11])('keeps expansions while following %i calls and freezes the list after scrolling away', (count) => {
        const following = jest.spyOn(VirtualizedThread, 'useIsFollowing').mockReturnValue(true)
        const tools = new Map<string, ToolInvocation>()
        const makeGroup = (length: number): ActivityGroup => ({
            id: 'streaming',
            type: 'activity_group',
            items: Array.from({ length }, (_, index) => {
                const id = `call-${index}`
                tools.set(id, {
                    toolCallId: id,
                    rawServerName: 'example',
                    rawToolName: 'read',
                    input: {},
                    status: 'completed',
                    contentBlocks: [],
                })
                return { id, type: 'tool_invocation', toolCallId: id }
            }),
        })
        const renderGroup = (group: ActivityGroup): JSX.Element => (
            <ThreadActivityGroup
                group={group}
                toolInvocations={tools}
                active
                cancelled={false}
                renderItem={(item) => (
                    <Activity
                        id={item.id}
                        title={item.id}
                        status="completed"
                        autoExpand={false}
                        details={`Details for ${item.id}`}
                    />
                )}
            />
        )
        const { rerender } = render(renderGroup(makeGroup(count)))
        fireEvent.click(screen.getByTestId('thread-activity-toggle'))
        fireEvent.click(screen.getAllByTestId('thread-tool-chain').at(-1)!.querySelector('[role="button"]')!)
        fireEvent.click(screen.getByText(`call-${count - 1}`))
        expect(screen.getByText(`Details for call-${count - 1}`)).toBeVisible()

        rerender(renderGroup(makeGroup(count + 1)))
        expect(screen.getByText(`call-${count}`)).toBeVisible()
        expect(screen.getByText(`Details for call-${count - 1}`)).toBeVisible()
        expect(screen.queryByTestId('thread-activity-refresh')).not.toBeInTheDocument()

        following.mockReturnValue(false)
        rerender(renderGroup(makeGroup(count + 2)))
        expect(screen.queryByText(`call-${count + 1}`)).not.toBeInTheDocument()
        expect(screen.getByTestId('thread-activity-refresh')).toHaveTextContent('Show 1 new activity')
        expect(screen.getByText(`Details for call-${count - 1}`)).toBeVisible()

        following.mockReturnValue(true)
        rerender(renderGroup(makeGroup(count + 2)))
        expect(screen.getByText(`call-${count + 1}`)).toBeVisible()
        expect(screen.queryByTestId('thread-activity-refresh')).not.toBeInTheDocument()
        expect(screen.getByText(`Details for call-${count - 1}`)).toBeVisible()
    })

    it('collapses consecutive tools into a chain while keeping failures and individual calls accessible', () => {
        const tools = new Map<string, ToolInvocation>(
            ['first', 'second', 'third'].map((id, index) => [
                id,
                {
                    toolCallId: id,
                    rawServerName: 'posthog',
                    rawToolName: 'exec',
                    input: { command: 'call execute-sql {}' },
                    status: index === 1 ? 'failed' : 'completed',
                    contentBlocks: [],
                },
            ])
        )
        render(
            <ThreadActivityGroup
                group={{
                    id: 'group',
                    type: 'activity_group',
                    items: [...tools.keys()].map((id) => ({ id, type: 'tool_invocation', toolCallId: id })),
                }}
                toolInvocations={tools}
                active={false}
                cancelled={false}
                renderItem={(item) => <div>{item.id}</div>}
            />
        )
        fireEvent.click(screen.getByTestId('thread-activity-toggle'))
        const chain = screen.getByTestId('thread-tool-chain')
        expect(chain).toHaveTextContent('execute-sql· 3 calls· 1 failed')
        expect(screen.queryByText('first')).not.toBeInTheDocument()
        fireEvent.click(chain.querySelector('[role="button"]')!)
        for (const id of tools.keys()) {
            expect(screen.getByText(id)).toBeVisible()
        }
    })

    it('reveals thought-only activity with one click and keeps streamed text readable when a tool arrives', () => {
        const tools = new Map<string, ToolInvocation>()
        const group: ActivityGroup = {
            id: 'thoughts',
            type: 'activity_group',
            items: [{ id: 'thought-1', type: 'assistant_thought', text: 'Compare the available approaches.' }],
        }
        const renderGroup = (value: ActivityGroup): JSX.Element => (
            <ThreadActivityGroup
                group={value}
                toolInvocations={tools}
                active
                cancelled={false}
                renderItem={(item) =>
                    item.type === 'assistant_thought' ? (
                        <ReasoningAnswer id={item.id} content={item.text ?? ''} completed />
                    ) : (
                        <div>{item.id}</div>
                    )
                }
            />
        )
        const { rerender } = render(renderGroup(group))
        fireEvent.click(screen.getByRole('button', { name: 'Thinking' }))
        expect(screen.getByText('Compare the available approaches.')).toBeVisible()
        expect(screen.getAllByRole('button')).toHaveLength(1)

        const updatedThought = { ...group.items[0], text: 'Compare the approaches and check the source.' }
        tools.set('call-1', {
            toolCallId: 'call-1',
            rawServerName: 'example',
            rawToolName: 'read',
            input: {},
            status: 'in_progress',
            contentBlocks: [],
        })
        rerender(
            renderGroup({
                ...group,
                items: [updatedThought, { id: 'call-1', type: 'tool_invocation', toolCallId: 'call-1' }],
            })
        )
        expect(screen.getByText(updatedThought.text)).toBeVisible()
        expect(screen.queryByText('call-1')).not.toBeInTheDocument()
        expect(screen.getByTestId('thread-activity-refresh')).toHaveTextContent('Show 1 new activity')
    })

    it('keeps the inspected rows stable while new calls arrive and adds hidden failures without replacing them', async () => {
        const tools = new Map<string, ToolInvocation>(
            Array.from({ length: 12 }, (_, index) => {
                const id = `call-${index}`
                return [
                    id,
                    {
                        toolCallId: id,
                        rawServerName: 'example',
                        rawToolName: index % 2 === 0 ? 'read' : 'search',
                        input: {},
                        status: 'in_progress',
                        contentBlocks: [],
                    },
                ]
            })
        )
        const group: ActivityGroup = {
            id: 'group',
            type: 'activity_group',
            items: [...tools.keys()].slice(0, 11).map((id) => ({ id, type: 'tool_invocation', toolCallId: id })),
        }
        const renderGroup = (value: ActivityGroup): JSX.Element => (
            <ThreadActivityGroup
                group={value}
                toolInvocations={tools}
                active={false}
                cancelled={false}
                renderItem={(item) => (
                    <div data-attr="test-activity-row">
                        {item.id}: {tools.get(item.id)?.status}
                    </div>
                )}
            />
        )
        const { rerender } = render(renderGroup(group))
        fireEvent.click(screen.getByTestId('thread-activity-toggle'))
        expect(screen.getAllByTestId('test-activity-row')).toHaveLength(5)
        tools.set('call-10', { ...tools.get('call-10')!, status: 'failed' })
        tools.set('call-5', { ...tools.get('call-5')!, status: 'failed' })
        const next: ActivityGroup = {
            ...group,
            items: [...group.items, { id: 'call-11', type: 'tool_invocation', toolCallId: 'call-11' }],
        }
        rerender(renderGroup(next))
        expect(screen.getByTestId('thread-activity-toggle')).toHaveTextContent('2 tool calls failed')
        expect(screen.getByText('call-10: failed')).toBeInTheDocument()
        expect(screen.queryByText('call-11: in_progress')).not.toBeInTheDocument()
        fireEvent.click(screen.getByTestId('thread-activity-refresh'))
        expect(screen.getByText('call-11: in_progress')).toBeInTheDocument()
        fireEvent.click(screen.getByTestId('thread-activity-failures'))
        expect(screen.getAllByTestId('test-activity-row')).toHaveLength(6)
        expect(screen.getByText('call-5: failed')).toBeInTheDocument()
        expect(screen.getByText('call-10: failed')).toBeInTheDocument()
        expect(screen.getByText('call-11: in_progress')).toBeInTheDocument()
        fireEvent.click(screen.getByTestId('thread-activity-failures'))
        await waitFor(() => expect(screen.queryByText('call-5: failed')).not.toBeInTheDocument())
        expect(screen.getAllByTestId('test-activity-row')).toHaveLength(5)
    })

    it('pages additional failures without changing the ordinary activity page or duplicating visible calls', () => {
        const tools = new Map<string, ToolInvocation>(
            Array.from({ length: 300 }, (_, index) => {
                const id = `failure-${index}`
                return [
                    id,
                    {
                        toolCallId: id,
                        rawServerName: 'example',
                        rawToolName: index % 2 === 0 ? 'read' : 'search',
                        input: {},
                        status: 'failed',
                        contentBlocks: [],
                    },
                ]
            })
        )
        const group: ActivityGroup = {
            id: 'failures',
            type: 'activity_group',
            items: [...tools.keys()].map((id) => ({ id, type: 'tool_invocation', toolCallId: id })),
        }
        render(
            <ThreadActivityGroup
                group={group}
                toolInvocations={tools}
                active={false}
                cancelled={false}
                renderItem={(item) => <div data-attr="test-activity-row">{item.id}</div>}
            />
        )
        fireEvent.click(screen.getByTestId('thread-activity-toggle'))
        fireEvent.click(screen.getByTestId('thread-activity-more'))
        fireEvent.click(screen.getByTestId('thread-activity-next'))
        const originalRows = screen.getAllByTestId('test-activity-row').map((row) => row.textContent)
        fireEvent.click(screen.getByTestId('thread-activity-failures'))
        expect(screen.getAllByTestId('test-activity-row')).toHaveLength(25)
        fireEvent.click(screen.getByTestId('thread-activity-failures-next'))
        const rows = screen.getAllByTestId('test-activity-row').map((row) => row.textContent)
        expect(new Set(rows).size).toBe(25)
        originalRows.forEach((text) => expect(rows).toContain(text))
        expect(screen.getByText('Page 2 of 30')).toBeInTheDocument()
    })
})
