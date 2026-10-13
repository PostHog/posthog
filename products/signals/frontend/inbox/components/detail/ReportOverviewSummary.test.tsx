import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { resolveChartPlacements } from '../../utils/chartPlacement'
import { ReportOverviewSummary } from './ReportOverviewSummary'

describe('ReportOverviewSummary', () => {
    afterEach(cleanup)

    it('keeps supporting text and reference definitions available after the next action', async () => {
        const user = userEvent.setup()
        const onToggle = jest.fn()
        const summary = [
            'The form rejects valid input.',
            '## Investigation',
            'Check the [source][source].',
            '[Evidence][evidence]',
            '## Solution',
            'Keep the entered value.',
            '## Impact',
            '[Impact](chart:impact)',
            '## Problem',
            'The handler clears the field.',
            '[source]: https://example.com/evidence',
            '[evidence]: chart:evidence',
        ].join('\n\n')

        render(
            <ReportOverviewSummary
                summary={summary}
                chartPlacements={resolveChartPlacements(summary, new Set(['impact', 'evidence']))}
                nextAction={<button>Implement</button>}
                onToggleAnalysis={onToggle}
            />
        )

        expect(screen.getAllByRole('heading').map((heading) => heading.textContent)).toEqual([
            'Problem',
            'Impact',
            'Solution',
            'Next step',
        ])
        expect(screen.getByText('Implement')).toBeVisible()
        expect(screen.queryByText(/Check the/)).not.toBeInTheDocument()

        const expand = screen.getByText('Full analysis').closest('button')
        if (!expand) {
            throw new Error('Expected an analysis toggle')
        }
        await user.click(expand)

        expect(expand).toHaveAttribute('aria-expanded', 'true')
        expect(screen.getByText(/Check the/)).toHaveTextContent('[source]: https://example.com/evidence')
        expect(screen.getByText(/Check the/)).toHaveTextContent('[evidence]: chart:evidence')
        expect(onToggle).toHaveBeenCalledWith(false)
    })

    it.each([
        'Keep this complete report visible.\n\nThe qualification is also part of the finding.',
        '## Finding\n\nKeep this complete report visible.\n\n## Qualification\n\nThe qualification is also part of the finding.',
        '## Finding\n\nKeep this complete report visible.\n\n## Solution\n\nThe qualification is also part of the finding.',
    ])('does not collapse a report without recognized sections', (summary) => {
        render(
            <ReportOverviewSummary
                summary={summary}
                chartPlacements={resolveChartPlacements(summary, new Set())}
                onToggleAnalysis={jest.fn()}
            />
        )

        expect(screen.getByText(/Keep this complete report visible/)).toBeVisible()
        expect(screen.getByText(/The qualification is also part of the finding/)).toBeVisible()
        expect(screen.queryByText('Full analysis')).not.toBeInTheDocument()
    })
})
