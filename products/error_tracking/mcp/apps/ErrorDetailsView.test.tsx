import { cleanup, render, screen } from '@testing-library/react'
import { type ReactElement } from 'react'

import { ErrorDetailsView } from './ErrorDetailsView'

jest.mock(
    '@posthog/mcp-ui',
    () => ({
        DescriptionList: ({ items }: { items: { label: string; value: unknown }[] }): ReactElement => (
            <dl>
                {items.map((item) => (
                    <div key={item.label}>
                        {item.label}: {String(item.value)}
                    </div>
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
        Card: ({ children }: { children: ReactElement }): ReactElement => <div>{children}</div>,
        CardContent: ({ children }: { children: ReactElement }): ReactElement => <div>{children}</div>,
        Empty: ({ children }: { children: ReactElement }): ReactElement => <div>{children}</div>,
        EmptyDescription: ({ children }: { children: ReactElement }): ReactElement => <div>{children}</div>,
        EmptyHeader: ({ children }: { children: ReactElement }): ReactElement => <div>{children}</div>,
        EmptyTitle: ({ children }: { children: ReactElement }): ReactElement => <div>{children}</div>,
    }),
    { virtual: true }
)

jest.mock('./StackTraceView', () => ({ StackTraceView: (): null => null }))

describe('ErrorDetailsView', () => {
    afterEach(cleanup)

    it('shows synthetic exceptions from the canonical exception list', () => {
        render(
            <ErrorDetailsView
                data={{
                    results: [
                        {
                            properties: {
                                $exception_list: [
                                    {
                                        type: 'TypeError',
                                        value: 'Bad call',
                                        mechanism: { synthetic: true },
                                    },
                                ],
                            },
                        },
                    ],
                }}
            />
        )

        expect(screen.getByText('Synthetic')).toBeTruthy()
    })

    it('shows the aggregate instead of the empty state in summary mode', () => {
        render(
            <ErrorDetailsView
                data={{
                    summary: {
                        occurrences: 3,
                        users: 1,
                        sessions: 2,
                        top_browsers: ['Chrome', 'Safari'],
                        sample_session_ids: ['session-id-1', 'session-id-2'],
                    },
                }}
            />
        )

        expect(screen.queryByText('No error events')).toBeNull()
        expect(screen.getByText('Occurrences: 3')).toBeTruthy()
        expect(screen.getByText('Browsers: Chrome, Safari')).toBeTruthy()
        expect(screen.getByText('Sample session IDs: session-id-1, session-id-2')).toBeTruthy()
    })
})
