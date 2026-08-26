import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import { InboxOnboardingTakeover } from './InboxOnboarding'

// The manual-setup escape hatch pulls in `inboxOnboardingLogic` (kea); it is unrelated to the card click.
jest.mock('./ManualSetupAction', () => ({ ManualSetupAction: () => null }))
jest.mock('../../inboxAnalytics', () => ({
    captureInboxWelcomeViewed: jest.fn(),
    captureInboxWelcomeCommandCopied: jest.fn(),
}))
jest.mock('./meep', () => ({ playMeep: jest.fn() }))
jest.mock('lib/components/TZLabel', () => ({ TZLabel: ({ time }: { time: string }) => <span>{time}</span> }))

describe('InboxOnboardingTakeover example cards', () => {
    beforeAll(() => {
        // jsdom does not implement scrollIntoView; stub it so the click handler can call it.
        Element.prototype.scrollIntoView = jest.fn()
    })
    afterEach(cleanup)

    it('answers a click on an example card by scrolling to the setup command and pulsing it', () => {
        const { container, getAllByLabelText } = render(<InboxOnboardingTakeover />)
        // A dead click leaves the DOM unchanged; the pulse ring must be absent before the click.
        expect(container.querySelector('.InboxOnboarding__commandPulse')).toBeNull()

        const overlays = getAllByLabelText(/Jump to the setup command/i)
        expect(overlays.length).toBeGreaterThan(0)
        fireEvent.click(overlays[0])

        expect(Element.prototype.scrollIntoView).toHaveBeenCalled()
        expect(container.querySelector('.InboxOnboarding__commandPulse')).not.toBeNull()
    })
})
