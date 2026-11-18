import { fireEvent, render, screen } from '@testing-library/react'

import { ExperimentConclusionComment } from './ExperimentConclusionComment'

// jsdom has no layout, so the collapsed height and the full text height are stubbed per case.
const COLLAPSED_HEIGHT = 144

describe('ExperimentConclusionComment', () => {
    const clientHeight = Object.getOwnPropertyDescriptor(Element.prototype, 'clientHeight')
    const scrollHeight = Object.getOwnPropertyDescriptor(Element.prototype, 'scrollHeight')

    function mockTextHeight(fullHeight: number): void {
        Object.defineProperty(Element.prototype, 'clientHeight', { configurable: true, get: () => COLLAPSED_HEIGHT })
        Object.defineProperty(Element.prototype, 'scrollHeight', { configurable: true, get: () => fullHeight })
    }

    afterEach(() => {
        Object.defineProperty(Element.prototype, 'clientHeight', clientHeight!)
        Object.defineProperty(Element.prototype, 'scrollHeight', scrollHeight!)
    })

    it('shows no toggle when the comment fits', () => {
        mockTextHeight(COLLAPSED_HEIGHT)
        render(<ExperimentConclusionComment comment="Shipped it." />)

        expect(screen.queryByTestId('experiment-conclusion-toggle')).toBeNull()
    })

    it('expands and collapses a comment taller than the cap', () => {
        mockTextHeight(COLLAPSED_HEIGHT * 4)
        render(<ExperimentConclusionComment comment="A long conclusion." />)

        const toggle = screen.getByTestId('experiment-conclusion-toggle')
        expect(toggle.textContent).toBe('Show more')
        expect(toggle.getAttribute('aria-expanded')).toBe('false')

        fireEvent.click(toggle)
        expect(toggle.textContent).toBe('Show less')
        expect(toggle.getAttribute('aria-expanded')).toBe('true')

        fireEvent.click(toggle)
        expect(toggle.textContent).toBe('Show more')
        expect(toggle.getAttribute('aria-expanded')).toBe('false')
    })
})
