import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { TransactionalEmailImpactApi } from 'products/messaging/frontend/generated/api.schemas'

import { emailImpactLogic } from './emailImpactLogic'
import { ImpactFunnelCard } from './ImpactFunnelCard'

const { ToastContainer } = jest.requireActual('react-toastify')

const IMPACT: TransactionalEmailImpactApi = {
    sent: 10,
    delivered: 9,
    opened: 5,
    clicked: 2,
    not_clicked: 7,
    untracked: 0,
    window_days: 7,
    after_click: { sends: 1, converted: 0 },
    without_click: { sends: 7, converted: 1 },
}

describe('ImpactFunnelCard', () => {
    let answer: [number, unknown]

    beforeEach(() => {
        useMocks({
            get: { '/api/projects/:team_id/transactional_email_log/impact/': () => answer },
        })
        initKeaTests()
    })

    afterEach(cleanup)

    const renderCard = (): void => {
        render(
            <Provider>
                <BindLogic logic={emailImpactLogic} props={{ workflowId: 'workflow-1' }}>
                    <ImpactFunnelCard />
                </BindLogic>
                <ToastContainer />
            </Provider>
        )
    }

    it('keeps the untracked note under an empty period', async () => {
        answer = [200, { ...IMPACT, sent: 0, delivered: 0, opened: 0, clicked: 0, not_clicked: 0, untracked: 3 }]
        renderCard()

        expect(await screen.findByText('No sends of this email were recorded in this period.')).toBeInTheDocument()
        expect(screen.getByText(/^3 sends in this period went out with tracking off/)).toBeInTheDocument()
    })

    it('draws opens and clicks that arrived before their sends', async () => {
        answer = [
            200,
            {
                ...IMPACT,
                sent: 0,
                delivered: 0,
                opened: 4,
                clicked: 1,
                not_clicked: 0,
                after_click: { sends: 1, converted: 0 },
                without_click: { sends: 0, converted: 0 },
            },
        ]
        renderCard()

        const funnel = await screen.findByTestId('email-impact-funnel')
        const barHeights = Array.from(funnel.querySelectorAll('li'), (step) => {
            const bar = step.firstElementChild?.firstElementChild as HTMLElement | null
            return bar?.style.height ?? null
        })
        expect(barHeights.slice(0, 4)).toEqual([null, null, '100%', '25%'])
    })

    it('shows a failed load once, in the card, and loads the funnel on Try again', async () => {
        answer = [500, { detail: 'Server error' }]
        renderCard()

        expect(
            await screen.findByText("This email's impact couldn't load. Try again, or pick a shorter period.")
        ).toBeInTheDocument()
        expect(screen.queryByText(/Load impact failed/)).not.toBeInTheDocument()

        answer = [200, IMPACT]
        fireEvent.click(screen.getAllByText('Try again')[0])

        expect(await screen.findByText('Delivered')).toBeInTheDocument()
        expect(screen.queryByText(/couldn't load/)).not.toBeInTheDocument()
    })
})
