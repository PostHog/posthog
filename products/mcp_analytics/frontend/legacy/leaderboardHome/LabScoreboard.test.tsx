import { render } from '@testing-library/react'

import { LabScoreboard } from './LabScoreboard'
import { type ScoreboardMetric } from './leaderboardShares'

describe('LabScoreboard', () => {
    it.each<[ScoreboardMetric, boolean, string | null]>([
        ['calls', false, null],
        ['users', false, 'No data in this date range.'],
        ['users', true, 'Could not load this data. Refresh to try again.'],
    ])(
        'with no %s data (failed=%s) keeps the toggle only when there is a view to switch away from',
        (metric, failed, message) => {
            const { container } = render(
                <LabScoreboard shares={[]} loading={false} failed={failed} metric={metric} onMetricChange={jest.fn()} />
            )

            expect(container.querySelector('[aria-label="Scoreboard metric"]') !== null).toBe(message !== null)
            expect(container.textContent).toContain(message ?? '')
        }
    )
})
