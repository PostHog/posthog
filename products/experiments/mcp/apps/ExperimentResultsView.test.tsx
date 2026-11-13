import { cleanup, render, screen } from '@testing-library/react'
import { type ReactElement, type ReactNode } from 'react'

import { type ExperimentResultsData, ExperimentResultsView } from './ExperimentResultsView'

jest.mock(
    '@posthog/mcp-ui',
    () => ({
        DataTable: ({
            columns,
            data,
        }: {
            columns: { key: string; render: (row: unknown) => ReactNode }[]
            data: unknown[]
        }): ReactElement => (
            <div>
                {data.map((row, rowIndex) => (
                    <div key={rowIndex}>
                        {columns.map((column) => (
                            <div key={column.key}>{column.render(row)}</div>
                        ))}
                    </div>
                ))}
            </div>
        ),
    }),
    { virtual: true }
)

jest.mock(
    '@posthog/quill',
    () => ({
        Badge: ({ children }: { children: ReactNode }): ReactElement => <span>{children}</span>,
        Card: ({ children }: { children: ReactNode }): ReactElement => <div>{children}</div>,
        CardContent: ({ children }: { children: ReactNode }): ReactElement => <div>{children}</div>,
        Progress: (): null => null,
    }),
    { virtual: true }
)

const resultsWithGoal = (goal: string): ExperimentResultsData => ({
    experiment: { id: 1, name: 'Faster checkout' },
    metrics: {
        primary: {
            results: [
                {
                    index: 0,
                    metric: { uuid: 'metric-1', name: 'Page load time', goal },
                    data: {
                        baseline: { key: 'control', number_of_samples: 500, sum: 1000 },
                        variant_results: [
                            { key: 'test', number_of_samples: 500, sum: 800, method: 'bayesian', chance_to_win: 0.1 },
                        ],
                    },
                },
            ],
        },
    },
})

describe('ExperimentResultsView', () => {
    afterEach(cleanup)

    it.each([
        ['increase', '10% to win'],
        ['decrease', '90% to win'],
    ])('shows the chance to win for a metric with the %s goal', (goal, expected) => {
        render(<ExperimentResultsView data={resultsWithGoal(goal)} />)

        expect(screen.getByText(expected)).toBeTruthy()
    })
})
