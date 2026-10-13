import { cleanup, render, screen } from '@testing-library/react'
import { type ReactElement } from 'react'

import { ErrorIssueView, formatBreakdownValues } from './ErrorIssueView'

jest.mock(
    '@posthog/mcp-ui',
    () => ({
        DescriptionList: ({ items }: { items: { label: string; value: string }[] }): ReactElement => (
            <dl>
                {items
                    .filter((item) => item.value)
                    .map((item) => (
                        <div key={item.label}>{`${item.label}: ${item.value}`}</div>
                    ))}
            </dl>
        ),
        formatDate: (value: string): string => value,
    }),
    { virtual: true }
)

jest.mock(
    '@posthog/quill',
    () => ({
        Badge: ({ children }: { children: ReactElement }): ReactElement => <span>{children}</span>,
        Button: ({ children }: { children: ReactElement }): ReactElement => <span>{children}</span>,
        Card: ({ children }: { children: ReactElement }): ReactElement => <div>{children}</div>,
        CardContent: ({ children }: { children: ReactElement }): ReactElement => <div>{children}</div>,
    }),
    { virtual: true }
)

describe('ErrorIssueView', () => {
    afterEach(cleanup)

    it('formats breakdown values with their counts', () => {
        expect(
            formatBreakdownValues([
                { value: '/checkout', count: 2 },
                { value: '/cart', count: 1 },
            ])
        ).toBe('/checkout (2), /cart (1)')
        expect(formatBreakdownValues(undefined)).toBe('')
    })

    it('shows the breakdown only for dimensions that have values', () => {
        render(
            <ErrorIssueView
                issue={{
                    id: 'issue-1',
                    name: 'TypeError',
                    breakdown: {
                        date_from: '2026-04-17T00:00:00Z',
                        date_to: '2026-04-24T00:00:00Z',
                        range_limited: true,
                        occurrences: 3,
                        sample_session_ids: ['session-1'],
                        top_values: { path: [{ value: '/checkout', count: 3 }] },
                    },
                }}
            />
        )

        expect(screen.getByText('Breakdown of 3 events (last 30 days of the range)')).toBeTruthy()
        expect(screen.getByText('Paths: /checkout (3)')).toBeTruthy()
        expect(screen.getByText('Sample session IDs: session-1')).toBeTruthy()
        expect(screen.queryByText(/Browsers:/)).toBeNull()
    })

    it('shows no breakdown when the response has none', () => {
        render(<ErrorIssueView issue={{ id: 'issue-1', name: 'TypeError' }} />)

        expect(screen.queryByText(/Breakdown of/)).toBeNull()
    })
})
