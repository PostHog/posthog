import { cleanup, render, screen } from '@testing-library/react'
import { type ReactElement } from 'react'

import { ErrorDetailsView } from './ErrorDetailsView'

jest.mock(
    '@posthog/mcp-ui',
    () => ({
        DescriptionList: (): null => null,
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
})
