import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createRef } from 'react'

import posthog from 'lib/posthog-typed'

import { mapPermissionOptions } from '../policy/permissionUtils'
import { PlanApprovalSelector } from './PlanApprovalActions'
import { RunEscapeBoundary } from './RunEscapeBoundary'

jest.mock('lib/posthog-typed', () => ({
    __esModule: true,
    default: { __loaded: true, capture: jest.fn() },
}))

describe('RunEscapeBoundary', () => {
    beforeEach(() => {
        jest.mocked(posthog.capture).mockClear()
        jest.spyOn(HTMLElement.prototype, 'getClientRects').mockReturnValue({ length: 1 } as DOMRectList)
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    it.each([
        ['chat', 'composer', true],
        ['chat', 'composer button', true],
        ['chat', 'message', true],
        ['chat', 'approval', true],
        ['chat', 'outside', false],
        ['composer', 'composer', true],
        ['composer', 'composer button', true],
        ['composer', 'message', false],
        ['composer', 'approval', true],
        ['composer', 'outside', false],
    ] as const)('%s handles Escape from %s: %s', (scope, target, expected) => {
        const onEscape = jest.fn()
        const textAreaRef = createRef<HTMLTextAreaElement>()
        render(
            <>
                <RunEscapeBoundary scope={scope} textAreaRef={textAreaRef} onEscape={onEscape}>
                    <form>
                        <textarea ref={textAreaRef} data-attr="composer" />
                        <button data-attr="composer button">Send</button>
                    </form>
                    <button data-attr="message">Message action</button>
                    <div data-attr="run-approval">
                        <button data-attr="approval">Approve</button>
                    </div>
                </RunEscapeBoundary>
                <button data-attr="outside">Another panel</button>
            </>
        )
        const element = screen.getByTestId(target)
        element.focus()
        fireEvent.keyDown(element, { key: 'Escape' })
        expect(onEscape).toHaveBeenCalledTimes(expected ? 1 : 0)
        expect(jest.mocked(posthog.capture).mock.calls).toEqual(
            expected ? [['keybind triggered', { keybind: 'escape', mechanism: 'hotkey' }]] : []
        )
    })

    it('retains main chat ownership while reading, and relinquishes it on another panel interaction', () => {
        const main = jest.fn()
        const sidebar = jest.fn()
        render(
            <>
                <RunEscapeBoundary scope="chat" onEscape={main}>
                    <p>Main message</p>
                </RunEscapeBoundary>
                <RunEscapeBoundary scope="composer" onEscape={sidebar}>
                    <p>Sidebar message</p>
                </RunEscapeBoundary>
            </>
        )
        fireEvent.pointerDown(screen.getByText('Main message'))
        fireEvent.keyDown(document.body, { key: 'Escape' })
        expect(main).toHaveBeenCalledTimes(1)
        fireEvent.pointerDown(screen.getByText('Sidebar message'))
        fireEvent.keyDown(document.body, { key: 'Escape' })
        expect(main).toHaveBeenCalledTimes(1)
        expect(sidebar).not.toHaveBeenCalled()
        expect(posthog.capture).toHaveBeenCalledTimes(1)
    })

    it.each([false, true])(
        'preserves focus ownership through attachment after another panel interaction=%s',
        (outside) => {
            const onEscape = jest.fn()
            const { unmount } = render(
                <div>
                    <RunEscapeBoundary scope="chat" focusKey="handoff" onEscape={onEscape}>
                        <p>Message</p>
                    </RunEscapeBoundary>
                    <p>Another panel</p>
                </div>
            )
            fireEvent.pointerDown(screen.getByText(outside ? 'Another panel' : 'Message'))
            unmount()
            render(
                <RunEscapeBoundary scope="chat" focusKey="handoff" onEscape={onEscape}>
                    <p>Attached message</p>
                </RunEscapeBoundary>
            )
            fireEvent.keyDown(document.body, { key: 'Escape' })
            expect(onEscape).toHaveBeenCalledTimes(outside ? 0 : 1)
        }
    )

    it.each(['chat', 'composer'] as const)(
        'scopes plan Escape and lets feedback editing finish first in %s',
        (scope) => {
            const onEscape = jest.fn()
            const legacyCancel = jest.fn()
            const options = mapPermissionOptions(
                [
                    { optionId: 'auto', name: 'Allow', kind: 'allow_once' },
                    { optionId: 'reject', name: 'Do it differently', kind: 'reject_with_feedback' },
                ],
                true
            )
            render(
                <RunEscapeBoundary scope={scope} onEscape={onEscape}>
                    <div data-attr="run-approval">
                        <PlanApprovalSelector
                            approveOptions={[options[0]]}
                            rejectOption={options[1]}
                            responding={false}
                            onApprove={jest.fn()}
                            onReject={jest.fn()}
                            onCancel={legacyCancel}
                        />
                    </div>
                </RunEscapeBoundary>
            )
            fireEvent.keyDown(document.body, { key: 'Escape' })
            expect(onEscape).toHaveBeenCalledTimes(scope === 'chat' ? 1 : 0)
            fireEvent.keyDown(document.body, { key: '2' })
            const input = screen.getByPlaceholderText(/tell the agent what to do differently/i)
            fireEvent.keyDown(input, { key: 'Escape' })
            expect(onEscape).toHaveBeenCalledTimes(scope === 'chat' ? 1 : 0)
            expect(legacyCancel).not.toHaveBeenCalled()
            expect(screen.getByTestId('run-approval')).toContainElement(document.activeElement as HTMLElement)
            fireEvent.keyDown(document.activeElement!, { key: 'Escape' })
            expect(onEscape).toHaveBeenCalledTimes(scope === 'chat' ? 2 : 1)
            expect(legacyCancel).not.toHaveBeenCalled()
        }
    )

    it.each([
        'editor',
        'hotkey-block',
        'disabled',
        'repeat',
        'isComposing',
        'metaKey',
        'ctrlKey',
        'altKey',
        'shiftKey',
        'unmounted',
    ])('leaves Escape alone for %s', (reason) => {
        const onEscape = jest.fn()
        const { unmount } = render(
            <RunEscapeBoundary scope="chat" onEscape={onEscape} disabled={reason === 'disabled'}>
                <div contentEditable data-attr="editor" />
                <button className="hotkey-block" data-attr="hotkey-block">
                    Blocked shortcut
                </button>
            </RunEscapeBoundary>
        )
        const target = ['editor', 'hotkey-block'].includes(reason) ? screen.getByTestId(reason) : document.body
        if (reason === 'unmounted') {
            unmount()
        }
        fireEvent.keyDown(target, { key: 'Escape', [reason]: true })
        expect(onEscape).not.toHaveBeenCalled()
        expect(posthog.capture).not.toHaveBeenCalled()
    })
})
