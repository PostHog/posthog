import { fireEvent, render } from '@testing-library/react'

import { ComposerModeShortcut } from './ComposerModeShortcut'

describe('ComposerModeShortcut', () => {
    it('cycles on Shift+Tab regardless of where focus sits', () => {
        const onCycle = jest.fn()
        render(<ComposerModeShortcut onCycle={onCycle} />)

        fireEvent.keyDown(document.body, { key: 'Tab', shiftKey: true })

        expect(onCycle).toHaveBeenCalledTimes(1)
    })

    it('ignores plain Tab, so normal focus navigation is untouched', () => {
        const onCycle = jest.fn()
        render(<ComposerModeShortcut onCycle={onCycle} />)

        fireEvent.keyDown(document.body, { key: 'Tab', shiftKey: false })

        expect(onCycle).not.toHaveBeenCalled()
    })

    it('yields to a handler that already consumed the key', () => {
        const onCycle = jest.fn()
        render(<ComposerModeShortcut onCycle={onCycle} />)
        window.addEventListener('keydown', (e) => e.preventDefault(), { capture: true, once: true })

        fireEvent.keyDown(document.body, { key: 'Tab', shiftKey: true })

        expect(onCycle).not.toHaveBeenCalled()
    })

    it('yields to open menus, which own Tab for their focus order', () => {
        const onCycle = jest.fn()
        const { getByText } = render(
            <>
                <ComposerModeShortcut onCycle={onCycle} />
                <div role="menu">
                    <button>Item</button>
                </div>
            </>
        )

        fireEvent.keyDown(getByText('Item'), { key: 'Tab', shiftKey: true })

        expect(onCycle).not.toHaveBeenCalled()
    })
})
