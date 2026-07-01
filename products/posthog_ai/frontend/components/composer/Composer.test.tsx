import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { Composer } from './Composer'

describe('Composer', () => {
    const onChange = jest.fn()
    const onSubmit = jest.fn()

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

    it('throws when a part is rendered outside Composer.Root', () => {
        // Silence the expected React error boundary log.
        const spy = jest.spyOn(console, 'error').mockImplementation(() => {})
        expect(() => render(<Composer.Submit />)).toThrow(/inside <Composer.Root>/)
        spy.mockRestore()
    })
})
