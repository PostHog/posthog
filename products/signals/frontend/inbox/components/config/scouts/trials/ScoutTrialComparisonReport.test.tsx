import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { ScoutTrialComparisonReport } from './ScoutTrialComparisonReport'
import { trialFixtureEvaluationWithJudgeError, trialFixtureLongReport, trialFixtureReport } from './scoutTrialsFixtures'

describe('ScoutTrialComparisonReport', () => {
    beforeEach(() => {
        initKeaTests(false)
    })

    afterEach(cleanup)

    it('uses the saved conclusion and does not infer a winner from an incomplete high score', () => {
        render(<ScoutTrialComparisonReport report={trialFixtureEvaluationWithJudgeError.report!} />)

        expect(screen.getByText('No clear winner')).not.toBeNull()
        expect(screen.getByText('100%')).not.toBeNull()
        expect(screen.getByText('1 run could not be judged')).not.toBeNull()
        expect(screen.queryByText(/Best in these runs/)).toBeNull()
    })

    it('keeps old reports readable without inventing a comparison conclusion', () => {
        render(<ScoutTrialComparisonReport report={{ ...trialFixtureReport, outcome: null }} />)

        expect(screen.getByText('No clear winner')).not.toBeNull()
        expect(screen.getByText(/This saved report has no comparison conclusion/)).not.toBeNull()
        expect(screen.queryByText(/Best in these runs/)).toBeNull()
    })

    it('counts rubric checks across repeats and keeps 12-check explanations inside their own rows', async () => {
        render(<ScoutTrialComparisonReport report={trialFixtureLongReport} />)

        expect(screen.getByText('22 passed')).not.toBeNull()
        expect(screen.getByText('24 passed')).not.toBeNull()
        expect(screen.queryByText('Evidence grounding')).toBeNull()

        await userEvent.click(screen.getAllByText('Run 1 of 2')[0])
        expect(screen.getByText('Evidence grounding')).not.toBeNull()
        expect(screen.getByText('Leave sensitive values out of reports')).not.toBeNull()
        expect(screen.queryByText(/The report states that three checkouts/)).toBeNull()
        expect(screen.queryByText('The captured scout output satisfies this check.')).toBeNull()

        await userEvent.click(screen.getByText('Evidence grounding'))
        expect(screen.getByText(/The report states that three checkouts/)).not.toBeNull()
        expect(screen.getByText('Three checkouts lost their delivery selection after coupon removal.')).not.toBeNull()
        expect(screen.getByText('Affected checkouts: 2.')).not.toBeNull()
        expect(screen.queryByText('The captured scout output satisfies this check.')).toBeNull()
    })
})
