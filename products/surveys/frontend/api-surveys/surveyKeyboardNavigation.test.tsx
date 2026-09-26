import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { advanceSurveyFocus, navigateSurveyChoices } from './surveyKeyboardNavigation'

describe('survey keyboard navigation', () => {
    afterEach(cleanup)

    beforeEach(() => {
        render(
            <>
                <textarea aria-label="Outside the survey" />
                <div onKeyDown={advanceSurveyFocus}>
                    <div data-survey-question="text">
                        <textarea aria-label="Text answer" />
                    </div>
                    <div data-survey-question="choice">
                        <input aria-label="Unselected choice" type="radio" name="choice" />
                        <input aria-label="Selected choice" type="radio" name="choice" defaultChecked />
                    </div>
                    <div data-survey-question="multiple" onKeyDown={navigateSurveyChoices}>
                        <input aria-label="First option" type="checkbox" />
                        <input aria-label="Disabled option" type="checkbox" disabled />
                        <input aria-label="Last option" type="checkbox" />
                    </div>
                    <button data-attr="api-survey-submit">Send feedback</button>
                </div>
            </>
        )
    })

    it.each(['ctrlKey', 'metaKey'])('moves from text to the selected choice with %s and Enter', (modifier) => {
        const text = screen.getByLabelText('Text answer')
        text.focus()
        fireEvent.keyDown(text, { key: 'Enter', [modifier]: true })
        expect(document.activeElement).toBe(screen.getByLabelText('Selected choice'))
        fireEvent.keyDown(document.activeElement!, { key: 'Enter' })
        expect(document.activeElement).toBe(screen.getByLabelText('First option'))
        fireEvent.keyDown(document.activeElement!, { key: 'Enter' })
        expect(document.activeElement).toBe(screen.getByText('Send feedback'))
    })

    it.each([
        { key: 'Enter' },
        { key: 'Enter', shiftKey: true },
        { key: 'Enter', ctrlKey: true, isComposing: true },
        { key: 'Enter', ctrlKey: true, altKey: true },
        { key: 'Enter', ctrlKey: true, repeat: true },
        { key: 'ArrowDown' },
        { key: 'Tab' },
    ])('preserves text editing and browser navigation for %j', (keys) => {
        const text = screen.getByLabelText('Text answer')
        text.focus()
        fireEvent.keyDown(text, keys)
        expect(document.activeElement).toBe(text)
    })

    it.each(['ArrowDown', 'ArrowRight', 'ArrowUp', 'ArrowLeft'])(
        'moves checkbox focus with %s without selecting',
        (key) => {
            const first = screen.getByLabelText('First option')
            const last = screen.getByLabelText('Last option')
            first.focus()
            fireEvent.keyDown(first, { key })
            expect(document.activeElement).toBe(last)
            expect((last as HTMLInputElement).checked).toBe(false)
            fireEvent.keyDown(last, { key })
            expect(document.activeElement).toBe(first)
            expect((first as HTMLInputElement).checked).toBe(false)
        }
    )

    it('leaves modified arrows and keys outside the survey alone', () => {
        const first = screen.getByLabelText('First option')
        first.focus()
        fireEvent.keyDown(first, { key: 'ArrowDown', shiftKey: true })
        expect(document.activeElement).toBe(first)
        const outside = screen.getByLabelText('Outside the survey')
        outside.focus()
        fireEvent.keyDown(outside, { key: 'Enter', ctrlKey: true })
        expect(document.activeElement).toBe(outside)
    })
})
