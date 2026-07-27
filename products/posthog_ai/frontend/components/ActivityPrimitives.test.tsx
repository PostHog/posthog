import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'

import { Activity } from './ActivityPrimitives'

function expectBefore(first: HTMLElement, second: HTMLElement): void {
    expect(first.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
}

describe('Activity', () => {
    it('renders details before the widget body', () => {
        render(
            <Activity
                id="tool-call"
                title={<span data-attr="header">Query trends</span>}
                status="in_progress"
                details={<div data-attr="details">Input</div>}
            >
                <div data-attr="widget">Visualization</div>
            </Activity>
        )

        const header = screen.getByTestId('header')
        const details = screen.getByTestId('details')
        const widget = screen.getByTestId('widget')

        expectBefore(header, details)
        expectBefore(details, widget)
    })
})
