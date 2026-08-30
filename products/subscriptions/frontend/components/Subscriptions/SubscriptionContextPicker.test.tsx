import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { SubscriptionContextApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionContextPicker } from './SubscriptionContextPicker'

interface MockTaxonomicPopoverProps {
    closeOnChange?: boolean
    disabledReason?: string
    onChange: (value: string | number, groupType: string, item: { id: number; name: string; short_id?: string }) => void
    selectedProperties?: Record<string, (string | number | null)[]>
    'data-attr'?: string
}

jest.mock('lib/components/TaxonomicPopover/TaxonomicPopover', () => {
    const { useState } = jest.requireActual('react')
    const { TaxonomicFilterGroupType } = jest.requireActual('lib/components/TaxonomicFilter/types')

    return {
        TaxonomicPopover: ({
            closeOnChange,
            disabledReason,
            onChange,
            selectedProperties,
            'data-attr': dataAttr,
        }: MockTaxonomicPopoverProps) => {
            const [isOpen, setIsOpen] = useState(false)
            const select = (
                value: string | number,
                groupType: string,
                item: { id: number; name: string; short_id?: string }
            ): void => {
                onChange(value, groupType, item)
                if (closeOnChange) {
                    setIsOpen(false)
                }
            }

            return (
                <div>
                    <button
                        data-attr={dataAttr}
                        disabled={Boolean(disabledReason)}
                        title={disabledReason}
                        onClick={() => setIsOpen(true)}
                    >
                        Add context
                    </button>
                    {isOpen ? (
                        <div data-testid="taxonomic-options">
                            <button
                                data-attr="pick-dashboard"
                                disabled={selectedProperties?.[TaxonomicFilterGroupType.Dashboards]?.includes(7)}
                                onClick={() =>
                                    select(7, TaxonomicFilterGroupType.Dashboards, {
                                        id: 7,
                                        name: 'Activation overview',
                                    })
                                }
                            >
                                Pick dashboard
                            </button>
                            <button
                                data-attr="pick-insight"
                                disabled={selectedProperties?.[TaxonomicFilterGroupType.Insights]?.includes(
                                    'signup-conversion'
                                )}
                                onClick={() =>
                                    select('signup-conversion', TaxonomicFilterGroupType.Insights, {
                                        id: 7,
                                        name: 'Signup conversion',
                                        short_id: 'signup-conversion',
                                    })
                                }
                            >
                                Pick insight
                            </button>
                            <button
                                data-attr="pick-second-dashboard"
                                onClick={() =>
                                    select(8, TaxonomicFilterGroupType.Dashboards, {
                                        id: 8,
                                        name: 'Revenue overview',
                                    })
                                }
                            >
                                Pick second dashboard
                            </button>
                            <button
                                data-attr="pick-second-insight"
                                onClick={() =>
                                    select('retention-trend', TaxonomicFilterGroupType.Insights, {
                                        id: 8,
                                        name: 'Retention trend',
                                        short_id: 'retention-trend',
                                    })
                                }
                            >
                                Pick second insight
                            </button>
                        </div>
                    ) : null}
                </div>
            )
        },
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

        await userEvent.click(screen.getByText('Add context'))
        await userEvent.click(screen.getByTestId('pick-dashboard'))
        await userEvent.click(screen.getByTestId('pick-insight'))

        expect(onAdd).toHaveBeenNthCalledWith(1, DASHBOARD_CONTEXT)
        expect(onAdd).toHaveBeenNthCalledWith(2, INSIGHT_CONTEXT)
    })

    it('marks selected targets by their real taxonomic values when reopened', async () => {
        const { rerender } = renderPicker([DASHBOARD_CONTEXT])

        await userEvent.click(screen.getByText('Add context'))
        expect(screen.getByTestId('pick-dashboard')).toBeDisabled()
        expect(screen.getByTestId('pick-insight')).toBeEnabled()

        rerender(
            <SubscriptionContextPicker
                contexts={[DASHBOARD_CONTEXT, INSIGHT_CONTEXT]}
                onAdd={jest.fn()}
                onRemove={jest.fn()}
            />
        )

        expect(screen.getByTestId('pick-dashboard')).toBeDisabled()
        expect(screen.getByTestId('pick-insight')).toBeDisabled()
    })

    it('removes the selected dashboard and insight from their tags', async () => {
        const onRemove = jest.fn()
        renderPicker([DASHBOARD_CONTEXT, INSIGHT_CONTEXT], jest.fn(), onRemove)

        const dashboardTag = screen.getByText('Activation overview').closest('[data-attr="ai-subscription-context"]')
        const insightTag = screen.getByText('Signup conversion').closest('[data-attr="ai-subscription-context"]')

        expect(dashboardTag).not.toBeNull()
        expect(insightTag).not.toBeNull()
        await userEvent.click(within(dashboardTag as HTMLElement).getByLabelText('Remove Activation overview'))
        await userEvent.click(within(insightTag as HTMLElement).getByLabelText('Remove Signup conversion'))

        expect(onRemove).toHaveBeenNthCalledWith(1, DASHBOARD_CONTEXT)
        expect(onRemove).toHaveBeenNthCalledWith(2, INSIGHT_CONTEXT)
    })

    it('closes after the third selection and disables additions at three combined contexts', async () => {
        const thirdContext: SubscriptionContextApi = {
            dashboard_id: 8,
            dashboard_name: 'Revenue overview',
        }
        const onAdd = jest.fn()
        const { rerender } = renderPicker([DASHBOARD_CONTEXT, INSIGHT_CONTEXT], onAdd)

        await userEvent.click(screen.getByText('Add context'))
        await userEvent.click(screen.getByTestId('pick-second-dashboard'))

        expect(onAdd).toHaveBeenCalledWith(thirdContext)
        expect(screen.queryByTestId('taxonomic-options')).not.toBeInTheDocument()

        rerender(
            <SubscriptionContextPicker
                contexts={[DASHBOARD_CONTEXT, INSIGHT_CONTEXT, thirdContext]}
                onAdd={onAdd}
                onRemove={jest.fn()}
            />
        )

        expect(screen.getByText('Add context')).toBeDisabled()
        expect(screen.getByText('Add context')).toHaveAttribute(
            'title',
            'You can add up to 3 dashboards and insights. Remove one to add another.'
        )
        expect(screen.queryByTestId('pick-second-insight')).not.toBeInTheDocument()
        expect(document.querySelector('[data-attr="ai-subscription-context-list"]')).toHaveClass('flex-wrap', 'min-w-0')
    })
})
