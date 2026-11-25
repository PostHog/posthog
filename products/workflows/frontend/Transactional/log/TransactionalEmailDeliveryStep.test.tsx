import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { TransactionalEmailDeliveryStep } from './TransactionalEmailDeliveryStep'

const EXPLANATION = 'Tracking was off for this send, so it records no opens or clicks.'

function renderUntrackedStep(): void {
    render(
        <ul>
            <TransactionalEmailDeliveryStep
                step={{ key: 'opened', label: 'Opened', state: 'untracked', at: null, detail: null, previousAt: null }}
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
        expect(await screen.findByText(EXPLANATION)).toBeTruthy()
    })

    it('opens the not tracked explanation on a tap', async () => {
        renderUntrackedStep()

        fireEvent.click(screen.getByText('Not tracked'))

        expect(await screen.findByText(EXPLANATION)).toBeTruthy()
    })
})
