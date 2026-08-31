import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'

import { SubscriptionDeliveryHistory } from './SubscriptionDeliveryHistory'

jest.mock('@posthog/lemon-ui', () => ({
    LemonButton: ({ children, onClick }: { children: ReactNode; onClick?: () => void }) => (
        <button onClick={onClick}>{children}</button>
    ),
    LemonBanner: ({
        children,
        action,
    }: {
        children: ReactNode
        action?: { children: ReactNode; onClick: () => void; disabled?: boolean; loading?: boolean }
    }) => (
        <div>
            {children}
            {action ? (
                <button disabled={action.disabled ?? action.loading} onClick={action.onClick}>
                    {action.children}
                </button>
            ) : null}
        </div>
    ),
    LemonDivider: () => null,
    LemonSelect: () => null,
    LemonTable: () => null,
    LemonTag: ({ children }: { children: ReactNode }) => <span>{children}</span>,
    Tooltip: ({ children }: { children: ReactNode }) => <>{children}</>,
}))

jest.mock('lib/components/TZLabel', () => ({ TZLabel: () => null }))
jest.mock('./SubscriptionAiReportDelivery', () => ({
    deliveryRowHasExpandableContent: () => false,
    ExpandedDeliveryRow: () => null,
    partialDeliveryTag: () => null,
}))
jest.mock('./SubscriptionDestinationCell', () => ({ SubscriptionDeliveryDestinationCell: () => null }))

describe('SubscriptionDeliveryHistory', () => {
    it('shows a retry when proactive history cannot be loaded', () => {
        const onRetryPulseHistory = jest.fn()
        const props = {
            deliveriesPage: { results: [], next: null, previous: null },
            deliveriesPageLoading: false,
            loadDeliveriesPage: jest.fn(),
            pulseHistoryLoadFailed: true,
            onRetryPulseHistory,
        }

        render(<SubscriptionDeliveryHistory {...props} />)

        expect(screen.getByText('Could not load proactive delivery details.')).toBeInTheDocument()
        fireEvent.click(screen.getByText('Retry'))
        expect(onRetryPulseHistory).toHaveBeenCalledTimes(1)
    })

    it('disables retry while proactive history is loading', () => {
        const onRetryPulseHistory = jest.fn()
        cleanup()

        render(
            <SubscriptionDeliveryHistory
                deliveriesPage={{ results: [], next: null, previous: null }}
                deliveriesPageLoading={false}
                loadDeliveriesPage={jest.fn()}
                pulseHistoryLoadFailed
                pulseHistoryLoading
                onRetryPulseHistory={onRetryPulseHistory}
            />
        )

        const retry = screen.getByText('Retry').closest('button')
        expect(retry).not.toBeNull()
        expect(retry).toBeDisabled()
        fireEvent.click(retry!)
        expect(onRetryPulseHistory).not.toHaveBeenCalled()
    })
})
