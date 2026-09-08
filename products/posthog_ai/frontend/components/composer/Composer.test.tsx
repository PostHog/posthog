import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createRef, useState } from 'react'

import { QueuedMessageList } from '../QueuedMessageList'
import { Composer } from './Composer'
import { ComposerSteerShortcut } from './ComposerSteerShortcut'

describe('Composer', () => {
    const onChange = jest.fn()
    const onSubmit = jest.fn()
    const onStop = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()
    })

    afterEach(() => {
        cleanup()
    })

    const renderComposer = (props: Partial<Parameters<typeof Composer.Root>[0]> = {}): ReturnType<typeof render> =>
        render(
            <Composer.Root value="" onChange={onChange} onSubmit={onSubmit} {...props}>
                <Composer.Frame>
                    <Composer.Field>
                        <Composer.Placeholder>Send a message…</Composer.Placeholder>
                        <Composer.Textarea data-attr="composer-input" />
                    </Composer.Field>
                </Composer.Frame>
                <Composer.Submit data-attr="composer-send" />
            </Composer.Root>
        )

    const getSend = (container: HTMLElement): HTMLButtonElement =>
        container.querySelector('[data-attr="composer-send"]') as HTMLButtonElement

    it.each(['Escape', 'Steer', 'Escape after closing a menu'])(
        'steers the saved queue once through %s without submitting the draft',
        (trigger) => {
            const steer = jest.fn()
            function QueuedComposer(): JSX.Element {
                const [pending, setPending] = useState(false)
                const textAreaRef = createRef<HTMLTextAreaElement>()
                const onSteer = (): void => {
                    setPending(true)
                    steer()
                }
                return (
                    <Composer.Root
                        value="unsent draft"
                        onChange={onChange}
                        onSubmit={onSubmit}
                        textAreaRef={textAreaRef}
                    >
                        <ComposerSteerShortcut textAreaRef={textAreaRef} onSteer={onSteer} disabled={pending} />
                        <QueuedMessageList
                            messages={[{ id: 'queued', content: 'saved message' }]}
                            onUpdate={jest.fn()}
                            onRemove={jest.fn()}
                            onSteer={onSteer}
                            steerPending={pending}
                        />
                        <Composer.Textarea data-attr="composer-input" />
                    </Composer.Root>
                )
            }
            render(<QueuedComposer />)
            if (trigger === 'Escape after closing a menu') {
                render(
                    <div aria-hidden="true">
                        <div role="listbox" />
                    </div>
                )
                jest.spyOn(document.querySelector('[role="listbox"]')!, 'getClientRects').mockReturnValue({
                    length: 1,
                } as DOMRectList)
            }
            const input = screen.getByTestId('composer-input')
            input.focus()
            for (let i = 0; i < 2; i++) {
                if (trigger.startsWith('Escape')) {
                    fireEvent.keyDown(input, { key: 'Escape' })
                } else {
                    fireEvent.click(screen.getByTestId('run-queue-steer'))
                }
            }
            expect(steer).toHaveBeenCalledTimes(1)
            expect(onSubmit).not.toHaveBeenCalled()
            expect(input).toHaveValue('unsent draft')
        }
    )

    it.each([
        'empty queue',
        'repeat',
        'composing',
        'menu',
        'dialog',
        'listbox',
        'other input',
        'queue editor',
        'hidden',
        'handled',
    ])('leaves Escape alone for %s', (reason) => {
        const textAreaRef = createRef<HTMLTextAreaElement>()
        const steer = jest.fn()
        const { container } = render(
            <div hidden={reason === 'hidden'}>
                <Composer.Root value="unsent draft" onChange={onChange} onSubmit={onSubmit} textAreaRef={textAreaRef}>
                    <ComposerSteerShortcut
                        textAreaRef={textAreaRef}
                        onSteer={steer}
                        disabled={reason === 'empty queue'}
                    />
                    <Composer.Textarea data-attr="composer-input" />
                    {reason === 'queue editor' && <textarea data-attr="run-queue-editor" />}
                </Composer.Root>
                <input data-attr="other-input" />
                {['menu', 'dialog', 'listbox'].includes(reason) && <div role={reason} />}
            </div>
        )
        const target =
            reason === 'other input' ? screen.getByTestId('other-input') : screen.getByTestId('composer-input')
        if (['menu', 'dialog', 'listbox'].includes(reason)) {
            jest.spyOn(screen.getByRole(reason), 'getClientRects').mockReturnValue({ length: 1 } as DOMRectList)
        }
        const event = new KeyboardEvent('keydown', {
            key: 'Escape',
            bubbles: true,
            cancelable: true,
            repeat: reason === 'repeat',
            isComposing: reason === 'composing',
        })
        if (reason === 'handled') {
            event.preventDefault()
        }
        target.dispatchEvent(event)
        expect(steer).not.toHaveBeenCalled()
        expect(event.defaultPrevented).toBe(reason === 'handled')
        expect(onSubmit).not.toHaveBeenCalled()
        expect(container.querySelector('textarea')).toHaveValue('unsent draft')
    })

    it('shows the placeholder only while empty', () => {
        const { rerender } = renderComposer()
        expect(screen.getByText('Send a message…')).toBeInTheDocument()

        rerender(
            <Composer.Root value="hi" onChange={onChange} onSubmit={onSubmit}>
                <Composer.Frame>
                    <Composer.Field>
                        <Composer.Placeholder>Send a message…</Composer.Placeholder>
                        <Composer.Textarea data-attr="composer-input" />
                    </Composer.Field>
                </Composer.Frame>
                <Composer.Submit data-attr="composer-send" />
            </Composer.Root>
        )
        expect(screen.queryByText('Send a message…')).not.toBeInTheDocument()
    })

    it('relays typing through onChange', () => {
        renderComposer()
        fireEvent.change(screen.getByRole('textbox'), { target: { value: 'hello' } })
        expect(onChange).toHaveBeenCalledWith('hello')
    })

    it('blocks submission and keeps the send button disabled while empty', () => {
        const { container } = renderComposer({ value: '   ' })
        expect(getSend(container)).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(getSend(container))
        expect(onSubmit).not.toHaveBeenCalled()
    })

    it('blocks submission while loading', () => {
        const { container } = renderComposer({ value: 'ship it', loading: true })
        expect(getSend(container)).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(getSend(container))
        expect(onSubmit).not.toHaveBeenCalled()
    })

    it('submits once when there is a non-empty value', () => {
        const { container } = renderComposer({ value: 'ship it' })
        fireEvent.click(getSend(container))
        expect(onSubmit).toHaveBeenCalledTimes(1)
    })

    it('submits on Enter and keeps Shift+Enter for new lines', () => {
        renderComposer({ value: 'ship it' })
        const textarea = screen.getByRole('textbox')

        fireEvent.keyDown(textarea, { key: 'Enter', shiftKey: true })
        expect(onSubmit).not.toHaveBeenCalled()

        fireEvent.keyDown(textarea, { key: 'Enter' })
        expect(onSubmit).toHaveBeenCalledTimes(1)
    })

    it('turns the send button into a Stop button while a turn is active with empty input', () => {
        const { container } = renderComposer({ value: '', isTurnActive: true, onStop })
        // Enabled (no "Type a message first"), and clicking cancels the run rather than submitting the form.
        expect(getSend(container)).not.toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(getSend(container))
        expect(onStop).toHaveBeenCalledTimes(1)
        expect(onSubmit).not.toHaveBeenCalled()
    })

    it('sends instead of stopping when a turn is active but the input has text', () => {
        const { container } = renderComposer({ value: 'follow up', isTurnActive: true, onStop })
        fireEvent.click(getSend(container))
        expect(onSubmit).toHaveBeenCalledTimes(1)
        expect(onStop).not.toHaveBeenCalled()
    })

    it('throws when a part is rendered outside Composer.Root', () => {
        // Silence the expected React error boundary log.
        const spy = jest.spyOn(console, 'error').mockImplementation(() => {})
        expect(() => render(<Composer.Submit />)).toThrow(/inside <Composer.Root>/)
        spy.mockRestore()
    })
})
