import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { RunComposer } from './RunComposer'

describe('RunComposer', () => {
    const onChange = jest.fn()
    const onSubmit = jest.fn()

    beforeEach(() => {
        jest.clearAllMocks()
    })

    afterEach(() => {
        cleanup()
    })

    const renderComposer = (props: Partial<Parameters<typeof RunComposer>[0]> = {}): ReturnType<typeof render> =>
        render(<RunComposer value="" onChange={onChange} onSubmit={onSubmit} {...props} />)

    const getSendButton = (container: HTMLElement): HTMLButtonElement =>
        container.querySelector('[data-attr="sandbox-composer-send"]') as HTMLButtonElement

    const getTextArea = (): HTMLTextAreaElement => screen.getByRole('textbox') as HTMLTextAreaElement

    it('shows the placeholder when empty and hides it once there is a value', () => {
        const { rerender } = renderComposer({ placeholder: 'Send a follow-up message…' })
        expect(screen.getByText('Send a follow-up message…')).toBeInTheDocument()

        rerender(
            <RunComposer value="hi" onChange={onChange} onSubmit={onSubmit} placeholder="Send a follow-up message…" />
        )
        expect(screen.queryByText('Send a follow-up message…')).not.toBeInTheDocument()
    })

    it('relays typing through onChange', () => {
        renderComposer()
        fireEvent.change(getTextArea(), { target: { value: 'hello' } })
        expect(onChange).toHaveBeenCalledWith('hello')
    })

    it('disables send and does not submit when the input is empty', () => {
        const { container } = renderComposer({ value: '   ' })
        expect(getSendButton(container)).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(getSendButton(container))
        expect(onSubmit).not.toHaveBeenCalled()
    })

    it('submits when there is a non-empty value', () => {
        const { container } = renderComposer({ value: 'ship it' })
        fireEvent.click(getSendButton(container))
        expect(onSubmit).toHaveBeenCalledTimes(1)
    })

    it('blocks submission while loading', () => {
        const { container } = renderComposer({ value: 'ship it', loading: true })
        expect(getSendButton(container)).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(getSendButton(container))
        expect(onSubmit).not.toHaveBeenCalled()
    })
})
