import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { PendingPermission, PermissionOption } from '../conversation/acp-types'
import { PermissionRequestView } from './PermissionRequestView'

function permission(overrides: Partial<PendingPermission> = {}): PendingPermission {
    return {
        requestId: 'r1',
        receivedAt: 1,
        toolCall: { toolCallId: 'tc-1', title: 'Run command', kind: 'execute' },
        options: [
            { optionId: 'allow_once', name: 'Allow', kind: 'allow_once' },
            { optionId: 'reject_once', name: 'Reject', kind: 'reject_once' },
        ],
        ...overrides,
    }
}

function button(name: string): HTMLButtonElement {
    return screen.getByRole('button', { name }) as HTMLButtonElement
}

describe('PermissionRequestView', () => {
    afterEach(() => {
        cleanup()
    })

    it('renders each option as a button labelled by its name', () => {
        render(<PermissionRequestView permission={permission()} onRespond={jest.fn()} />)

        expect(button('Allow')).toBeInTheDocument()
        expect(button('Reject')).toBeInTheDocument()
    })

    it('renders the tool call title as the header', () => {
        render(
            <PermissionRequestView
                permission={permission({ toolCall: { toolCallId: 'tc-1', title: 'Delete the table' } })}
                onRespond={jest.fn()}
            />
        )

        expect(screen.getByText('Delete the table')).toBeInTheDocument()
    })

    it('falls back to a generic header when the tool call has no title', () => {
        render(
            <PermissionRequestView
                permission={permission({ toolCall: { toolCallId: 'tc-1', title: '' } })}
                onRespond={jest.fn()}
            />
        )

        expect(screen.getByText('Permission required')).toBeInTheDocument()
    })

    it('calls onRespond with the option id when an allow option is clicked', async () => {
        const onRespond = jest.fn()
        render(<PermissionRequestView permission={permission()} onRespond={onRespond} />)

        await userEvent.click(button('Allow'))

        expect(onRespond).toHaveBeenCalledTimes(1)
        expect(onRespond).toHaveBeenCalledWith('allow_once')
    })

    it('calls onRespond with the option id when a reject option is clicked', async () => {
        const onRespond = jest.fn()
        render(<PermissionRequestView permission={permission()} onRespond={onRespond} />)

        await userEvent.click(button('Reject'))

        expect(onRespond).toHaveBeenCalledTimes(1)
        expect(onRespond).toHaveBeenCalledWith('reject_once')
    })

    it('treats allow_always as a non-reject (allow) option', async () => {
        const onRespond = jest.fn()
        render(
            <PermissionRequestView
                permission={permission({
                    options: [{ optionId: 'allow_always', name: 'Always allow', kind: 'allow_always' }],
                })}
                onRespond={onRespond}
            />
        )

        await userEvent.click(button('Always allow'))

        expect(onRespond).toHaveBeenCalledWith('allow_always')
    })

    it('applies danger styling to reject options and default styling to allow options', () => {
        render(<PermissionRequestView permission={permission()} onRespond={jest.fn()} />)

        expect(button('Reject').className).toContain('LemonButton--status-danger')
        expect(button('Allow').className).not.toContain('LemonButton--status-danger')
    })

    it('treats reject_always as a reject option', () => {
        render(
            <PermissionRequestView
                permission={permission({
                    options: [{ optionId: 'reject_always', name: 'Never', kind: 'reject_always' }],
                })}
                onRespond={jest.fn()}
            />
        )

        expect(button('Never').className).toContain('LemonButton--status-danger')
    })

    it('disables every option button when disabled is set', () => {
        render(<PermissionRequestView permission={permission()} onRespond={jest.fn()} disabled />)

        expect(button('Allow')).toHaveAttribute('aria-disabled', 'true')
        expect(button('Reject')).toHaveAttribute('aria-disabled', 'true')
    })

    it('does not call onRespond when a disabled button is clicked', async () => {
        const onRespond = jest.fn()
        render(<PermissionRequestView permission={permission()} onRespond={onRespond} disabled />)

        await userEvent.click(button('Allow'))

        expect(onRespond).not.toHaveBeenCalled()
    })

    it('renders plan markdown from rawInput.plan', () => {
        render(
            <PermissionRequestView
                permission={permission({
                    toolCall: { toolCallId: 'tc-1', title: 'Plan', kind: 'plan', rawInput: { plan: '# My plan' } },
                })}
                onRespond={jest.fn()}
            />
        )

        // react-markdown is mocked in jest to render raw markdown text, so the '#' is preserved.
        expect(screen.getByText('My plan', { exact: false })).toBeInTheDocument()
    })

    it('renders plan markdown from text content when rawInput has no plan', () => {
        render(
            <PermissionRequestView
                permission={permission({
                    toolCall: {
                        toolCallId: 'tc-1',
                        title: 'Plan',
                        content: [{ type: 'content', content: { type: 'text', text: 'Plan from content' } }],
                    },
                })}
                onRespond={jest.fn()}
            />
        )

        expect(screen.getByText('Plan from content')).toBeInTheDocument()
    })

    it('does not render a plan container when there is no plan', () => {
        const { container } = render(<PermissionRequestView permission={permission()} onRespond={jest.fn()} />)

        expect(container.querySelector('.max-h-\\[40vh\\]')).toBeNull()
    })

    // Parity gap (major): the WEB version accepts a customInput param in the onRespond
    // signature but renders no input field, so custom input can never be supplied.
    it('renders no text input field for custom input', () => {
        const { container } = render(<PermissionRequestView permission={permission()} onRespond={jest.fn()} />)

        expect(container.querySelector('input')).toBeNull()
        expect(container.querySelector('textarea')).toBeNull()
    })

    // Parity gap (major): single-click buttons only, no checkboxes for multi-select.
    it('renders no checkboxes for multi-select selection', () => {
        const { container } = render(<PermissionRequestView permission={permission()} onRespond={jest.fn()} />)

        expect(container.querySelector('input[type="checkbox"]')).toBeNull()
    })

    // Parity gap (minor): option metadata / descriptions are not rendered.
    it('does not render option descriptions or metadata text', () => {
        const optionWithMeta: PermissionOption = {
            optionId: 'allow_once',
            name: 'Allow',
            kind: 'allow_once',
            _meta: { description: 'Allow this one command' },
        }
        render(<PermissionRequestView permission={permission({ options: [optionWithMeta] })} onRespond={jest.fn()} />)

        expect(screen.queryByText('Allow this one command')).toBeNull()
    })

    it('renders one button per option, preserving order', () => {
        render(
            <PermissionRequestView
                permission={permission({
                    options: [
                        { optionId: 'a', name: 'First', kind: 'allow_once' },
                        { optionId: 'b', name: 'Second', kind: 'allow_always' },
                        { optionId: 'c', name: 'Third', kind: 'reject_once' },
                    ],
                })}
                onRespond={jest.fn()}
            />
        )

        const buttons = screen.getAllByRole('button')
        expect(buttons.map((b) => b.textContent)).toEqual(['First', 'Second', 'Third'])
    })
})
