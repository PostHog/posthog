import '@testing-library/jest-dom'

import { cleanup, render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { useState } from 'react'

import type { SubscriptionContextApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionContextPicker } from './SubscriptionContextPicker'
import { CONTEXT_READ_BUDGET, MAX_SELECTED_CONTEXTS } from './utils'

interface MockTaxonomicPopoverProps {
    closeOnChange?: boolean
    disabledReason?: string
    onChange: (value: string | number, groupType: string, item: { id: number; name: string; short_id?: string }) => void
    selectedProperties?: Record<string, (string | number | null)[]>
    'data-attr'?: string
}

jest.mock('lib/components/TaxonomicPopover/TaxonomicPopover', () => {
    const { useEffect, useRef, useState } = jest.requireActual('react')
    const { TaxonomicFilterGroupType } = jest.requireActual('lib/components/TaxonomicFilter/types')

    return {
        TaxonomicPopover: ({
            closeOnChange,
            disabledReason,
            onChange,
            selectedProperties,
            'data-attr': dataAttr,
        }: MockTaxonomicPopoverProps): JSX.Element => {
            const [isOpen, setIsOpen] = useState(false)
            const previousCloseOnChange = useRef(closeOnChange)

            useEffect(() => {
                if (previousCloseOnChange.current !== closeOnChange) {
                    setIsOpen(false)
                    previousCloseOnChange.current = closeOnChange
                }
            }, [closeOnChange])

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
                        <div data-attr="taxonomic-options">
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

function StatefulPicker({ initialContexts = [] }: { initialContexts?: SubscriptionContextApi[] }): JSX.Element {
    const [contexts, setContexts] = useState<SubscriptionContextApi[]>(initialContexts)

    return (
        <SubscriptionContextPicker
            contexts={contexts}
            onAdd={(context) => setContexts((current) => [...current, context])}
            onRemove={(context) => setContexts((current) => current.filter((candidate) => candidate !== context))}
        />
    )
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

    it('keeps the picker open across selections, then closes and disables at the cap', async () => {
        const prefilled: SubscriptionContextApi[] = Array.from({ length: MAX_SELECTED_CONTEXTS - 2 }, (_, index) => ({
            dashboard_id: 100 + index,
            dashboard_name: `Prefilled dashboard ${index}`,
        }))
        render(<StatefulPicker initialContexts={prefilled} />)
        await userEvent.click(screen.getByText('Add context'))
        await userEvent.click(screen.getByTestId('pick-dashboard'))

        expect(screen.getByTestId('taxonomic-options')).toBeInTheDocument()

        await userEvent.click(screen.getByTestId('pick-insight'))

        expect(screen.queryByTestId('taxonomic-options')).not.toBeInTheDocument()
        expect(screen.getByText('Add context')).toBeDisabled()
        expect(screen.getByText('Add context')).toHaveAttribute(
            'title',
            `You can add up to ${MAX_SELECTED_CONTEXTS} dashboards and insights. Remove one to add another.`
        )
        expect(document.querySelector('[data-attr="ai-subscription-context-list"]')).toHaveClass('flex-wrap', 'min-w-0')
    })

    it.each([
        [
            'unknown counts fall back to the budget copy',
            undefined,
            undefined,
            `Each report reads up to ${CONTEXT_READ_BUDGET} insights from this context.`,
        ],
        [
            'a known total within the budget is stated exactly',
            { 7: 4 },
            5,
            'Each report reads 5 insights from this context.',
        ],
        [
            'a total over the budget states what gets read',
            { 7: CONTEXT_READ_BUDGET + 5 },
            CONTEXT_READ_BUDGET + 6,
            `Each report reads ${CONTEXT_READ_BUDGET} of the ${CONTEXT_READ_BUDGET + 6} insights in this context.`,
        ],
    ])('shows the read counter: %s', (_name, insightCounts, readTotal, expected) => {
        render(
            <SubscriptionContextPicker
                contexts={[DASHBOARD_CONTEXT, INSIGHT_CONTEXT]}
                insightCounts={insightCounts}
                readTotal={readTotal}
                onAdd={jest.fn()}
                onRemove={jest.fn()}
            />
        )

        expect(screen.getByText(expected)).toBeInTheDocument()
        if (insightCounts?.[7] !== undefined) {
            expect(screen.getByText(`Activation overview (${insightCounts[7]})`)).toBeInTheDocument()
        } else {
            expect(screen.getByText('Activation overview')).toBeInTheDocument()
        }
    })
})
