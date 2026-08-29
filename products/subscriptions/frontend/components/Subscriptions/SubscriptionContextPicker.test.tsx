import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { SubscriptionContextApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionContextPicker } from './SubscriptionContextPicker'

interface MockTaxonomicPopoverProps {
    disabledReason?: string
    onChange: (value: number, groupType: string, item: { id: number; name: string; short_id?: string }) => void
    selectedProperties?: Record<string, (string | number | null)[]>
    'data-attr'?: string
}

jest.mock('lib/components/TaxonomicPopover/TaxonomicPopover', () => {
    const { TaxonomicFilterGroupType } = jest.requireActual('lib/components/TaxonomicFilter/types')

    return {
        TaxonomicPopover: ({
            disabledReason,
            onChange,
            selectedProperties,
            'data-attr': dataAttr,
        }: MockTaxonomicPopoverProps) => (
            <div>
                <button data-attr={dataAttr} disabled={Boolean(disabledReason)} title={disabledReason}>
                    Add context
                </button>
                <button
                    data-testid="pick-dashboard"
                    disabled={
                        Boolean(disabledReason) ||
                        selectedProperties?.[TaxonomicFilterGroupType.Dashboards]?.includes(7)
                    }
                    onClick={() =>
                        onChange(7, TaxonomicFilterGroupType.Dashboards, {
                            id: 7,
                            name: 'Activation overview',
                        })
                    }
                >
                    Pick dashboard
                </button>
                <button
                    data-testid="pick-insight"
                    disabled={
                        Boolean(disabledReason) || selectedProperties?.[TaxonomicFilterGroupType.Insights]?.includes(7)
                    }
                    onClick={() =>
                        onChange(7, TaxonomicFilterGroupType.Insights, {
                            id: 7,
                            name: 'Signup conversion',
                            short_id: 'signup-conversion',
                        })
                    }
                >
                    Pick insight
                </button>
            </div>
        ),
    }
})

const DASHBOARD_CONTEXT: SubscriptionContextApi = {
    dashboard_id: 7,
    dashboard_name: 'Activation overview',
}

const INSIGHT_CONTEXT: SubscriptionContextApi = {
    insight_id: 7,
    insight_short_id: 'signup-conversion',
    insight_name: 'Signup conversion',
}

function renderPicker(
    contexts: SubscriptionContextApi[] = [],
    onAdd: jest.Mock = jest.fn(),
    onRemove: jest.Mock = jest.fn()
): ReturnType<typeof render> {
    return render(<SubscriptionContextPicker contexts={contexts} onAdd={onAdd} onRemove={onRemove} />)
}

describe('SubscriptionContextPicker', () => {
    afterEach(cleanup)

    it('adapts dashboard and insight selections to generated context values', async () => {
        const onAdd = jest.fn()
        renderPicker([], onAdd)

        await userEvent.click(screen.getByRole('button', { name: 'Pick dashboard' }))
        await userEvent.click(screen.getByRole('button', { name: 'Pick insight' }))

        expect(onAdd).toHaveBeenNthCalledWith(1, DASHBOARD_CONTEXT)
        expect(onAdd).toHaveBeenNthCalledWith(2, INSIGHT_CONTEXT)
    })

    it('marks selected targets by resource type', () => {
        const { rerender } = renderPicker([DASHBOARD_CONTEXT])

        expect(screen.getByRole('button', { name: 'Pick dashboard' })).toBeDisabled()
        expect(screen.getByRole('button', { name: 'Pick insight' })).toBeEnabled()

        rerender(
            <SubscriptionContextPicker
                contexts={[DASHBOARD_CONTEXT, INSIGHT_CONTEXT]}
                onAdd={jest.fn()}
                onRemove={jest.fn()}
            />
        )

        expect(screen.getByRole('button', { name: 'Pick dashboard' })).toBeDisabled()
        expect(screen.getByRole('button', { name: 'Pick insight' })).toBeDisabled()
    })

    it('removes the selected dashboard and insight from their tags', async () => {
        const onRemove = jest.fn()
        renderPicker([DASHBOARD_CONTEXT, INSIGHT_CONTEXT], jest.fn(), onRemove)

        const dashboardTag = screen.getByText('Activation overview').closest('[data-attr="ai-subscription-context"]')
        const insightTag = screen.getByText('Signup conversion').closest('[data-attr="ai-subscription-context"]')

        expect(dashboardTag).not.toBeNull()
        expect(insightTag).not.toBeNull()
        await userEvent.click(
            within(dashboardTag as HTMLElement).getByRole('button', { name: 'Remove Activation overview' })
        )
        await userEvent.click(
            within(insightTag as HTMLElement).getByRole('button', { name: 'Remove Signup conversion' })
        )

        expect(onRemove).toHaveBeenNthCalledWith(1, DASHBOARD_CONTEXT)
        expect(onRemove).toHaveBeenNthCalledWith(2, INSIGHT_CONTEXT)
    })

    it('wraps selected tags and disables additions at three combined contexts', () => {
        const thirdContext: SubscriptionContextApi = {
            insight_id: 8,
            insight_short_id: 'retention-trend',
            insight_name: 'Retention trend',
        }
        renderPicker([DASHBOARD_CONTEXT, INSIGHT_CONTEXT, thirdContext])

        expect(screen.getByText('Add context')).toBeDisabled()
        expect(screen.getByText('Add context')).toHaveAttribute(
            'title',
            'You can add up to 3 dashboards and insights. Remove one to add another.'
        )
        expect(document.querySelector('[data-attr="ai-subscription-context-list"]')).toHaveClass('flex-wrap', 'min-w-0')
    })
})
