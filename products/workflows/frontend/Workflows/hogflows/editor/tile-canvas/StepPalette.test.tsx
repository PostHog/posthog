import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { createRef } from 'react'

import { initKeaTests } from '~/test/init'

import { StepPalette } from './StepPalette'
import type { PaletteSection } from './tileCanvasModel'

const SECTIONS: PaletteSection[] = [
    {
        title: 'Delays',
        steps: [
            { type: 'delay', name: 'Delay', description: 'Pause.', config: { delay_duration: '1h' } },
            { type: 'wait_until_time_window', name: 'Time window', description: 'Hold.', config: {} as any },
        ],
    },
]

function renderPalette(): { onSelectStep: jest.Mock; onClose: jest.Mock; trigger: HTMLButtonElement } {
    const onSelectStep = jest.fn()
    const onClose = jest.fn()
    const triggerRef = createRef<HTMLButtonElement>()
    render(
        <>
            <button ref={triggerRef}>Add a step here</button>
            <StepPalette
                sections={SECTIONS}
                placeholder="Search steps"
                trigger={triggerRef}
                onSelectStep={onSelectStep}
                onClose={onClose}
            />
        </>
    )
    return { onSelectStep, onClose, trigger: triggerRef.current as HTMLButtonElement }
}

describe('StepPalette', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    it('points the search box at the highlighted option as the arrow keys move', () => {
        renderPalette()
        const search = screen.getByRole('combobox')

        fireEvent.keyDown(search, { key: 'ArrowDown' })

        const highlighted = screen.getByRole('option', { selected: true })
        expect(highlighted).toHaveTextContent('Time window')
        expect(search).toHaveAttribute('aria-activedescendant', highlighted.id)
        expect(screen.getByRole('listbox')).toContainElement(highlighted)
    })

    it('leaves Enter to an input method that is still composing a word', () => {
        const { onSelectStep } = renderPalette()

        fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Enter', isComposing: true })
        expect(onSelectStep).not.toHaveBeenCalled()

        fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Enter' })
        expect(onSelectStep).toHaveBeenCalledWith(SECTIONS[0].steps[0])
    })

    it('gives focus back to the button that opened it on Escape', () => {
        const { onClose, trigger } = renderPalette()

        fireEvent.keyDown(screen.getByRole('combobox'), { key: 'Escape' })

        expect(onClose).toHaveBeenCalled()
        expect(trigger).toHaveFocus()
    })
})
