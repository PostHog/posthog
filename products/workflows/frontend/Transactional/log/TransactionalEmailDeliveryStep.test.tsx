import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { TransactionalEmailDeliveryStep } from './TransactionalEmailDeliveryStep'

const OPENS_EXPLANATION = 'Open tracking was off for this send, so it records no opens.'
const CLICKS_EXPLANATION = 'Click tracking was off for this send, so it records no clicks.'

function renderUntrackedStep(key = 'opened', label = 'Opened'): void {
    render(
        <ul>
            <TransactionalEmailDeliveryStep
                step={{ key, label, state: 'untracked', at: null, detail: null, previousAt: null }}
                next={undefined}
            />
        </ul>
    )
}

describe('TransactionalEmailDeliveryStep', () => {
    afterEach(() => {
        cleanup()
    })

    it('opens the not tracked explanation when a keyboard user tabs to it', async () => {
        renderUntrackedStep()

        await userEvent.setup().tab()

        expect(document.activeElement).toBe(screen.getByText('Not tracked'))
        expect(await screen.findByText(OPENS_EXPLANATION)).toBeTruthy()
    })

    it.each([
        ['opened', 'Opened', OPENS_EXPLANATION],
        ['clicked', 'Clicked', CLICKS_EXPLANATION],
    ])('opens the not tracked explanation of the %s step on a tap', async (key, label, explanation) => {
        renderUntrackedStep(key, label)

        fireEvent.click(screen.getByText('Not tracked'))

        expect(await screen.findByText(explanation)).toBeTruthy()
    })
})
