import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import { ScoutTrialComparisonReport } from './ScoutTrialComparisonReport'
import { ScoutTrialRunDrawer } from './ScoutTrialRunDrawer'
import {
    trialFixtureEvaluationWithJudgeError,
    trialFixtureLongReport,
    trialFixtureReport,
    trialFixtureResult,
} from './scoutTrialsFixtures'

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
        expect(screen.queryByText(/Best in this trial/)).toBeNull()
    })

    it('keeps old reports readable without inventing a comparison conclusion', () => {
        render(<ScoutTrialComparisonReport report={{ ...trialFixtureReport, outcome: null }} />)

        expect(screen.getByText('No clear winner')).not.toBeNull()
        expect(screen.getByText(/This saved report has no comparison conclusion/)).not.toBeNull()
        expect(screen.queryByText(/Best in this trial/)).toBeNull()
    })

    it('counts rubric checks across repeats and keeps 12-check explanations inside their own rows', async () => {
        const openRun = jest.fn()
        render(<ScoutTrialComparisonReport report={trialFixtureLongReport} onSelectRun={openRun} />)

        expect(screen.getByText('22 / 24')).not.toBeNull()
        expect(screen.getByText('24 / 24')).not.toBeNull()
        expect(screen.getByText('Evidence grounding')).not.toBeNull()
        expect(screen.queryByText('Leave sensitive values out of reports')).toBeNull()

        await userEvent.click(screen.getAllByText('Run 1 of 2')[1])
        expect(openRun).toHaveBeenCalledWith(trialFixtureLongReport.runs[0].launch_id)
        cleanup()
        render(
            <ScoutTrialRunDrawer
                result={null}
                report={trialFixtureLongReport}
                launchId={trialFixtureLongReport.runs[0].launch_id}
                onClose={jest.fn()}
            />
        )
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

    it('shows every check by default for a short rubric and lets the reader filter differences', async () => {
        render(<ScoutTrialComparisonReport report={trialFixtureReport} />)
        expect(screen.getByText('Useful next step')).not.toBeNull()
        await userEvent.click(screen.getByText('Only checks that differ (1 of 2)'))
        expect(screen.queryByText('Useful next step')).toBeNull()
        expect(screen.getByText('Evidence grounding')).not.toBeNull()
    })

    it.each([
        ['failed', 'Failed · not judged'],
        ['cancelled', 'Stopped · not judged'],
    ])('preserves the saved %s status for excluded runs', (executionStatus, label) => {
        render(
            <ScoutTrialComparisonReport
                report={{
                    ...trialFixtureReport,
                    runs: trialFixtureReport.runs.map((run, index) =>
                        index === 0 ? { ...run, status: 'excluded', criteria: [] } : run
                    ),
                    evidence: trialFixtureReport.evidence.map((run, index) =>
                        index === 0 ? { ...run, execution_status: executionStatus } : run
                    ),
                }}
            />
        )

        expect(screen.getByText(label)).not.toBeNull()
    })

    it("does not show another trial's judge metadata for an individual history run", async () => {
        render(
            <ScoutTrialRunDrawer
                result={{ ...trialFixtureResult, launch_id: '00000000-0000-4000-8000-000000000099' }}
                report={trialFixtureReport}
                onClose={jest.fn()}
            />
        )

        await userEvent.click(screen.getByText('Technical details'))

        expect(screen.getByText('Not judged')).not.toBeNull()
        expect(screen.queryByText(trialFixtureReport.judge_model)).toBeNull()
        expect(screen.queryByText(trialFixtureReport.evaluation_id)).toBeNull()
    })

    it.each([
        [null, 'New report'],
        ['00000000-0000-4000-8000-000000000098', 'Updated existing report'],
    ])('shows captured changes when the report summary stays unchanged (%s)', async (sourceReportId, label) => {
        render(
            <ScoutTrialRunDrawer
                result={{
                    ...trialFixtureResult,
                    reports: [
                        {
                            id: '00000000-0000-4000-8000-000000000098',
                            source_report_id: sourceReportId,
                            document: { title: 'Saved checkout report', summary: 'The original report summary.' },
                            edits: [
                                {
                                    append_note: 'The latest check confirms the saved finding.',
                                    corroboration_only: true,
                                },
                            ],
                            evidence: [{ content: 'Delivery selection cleared after removing a coupon.' }],
                            artefacts: [{ type: 'note', content: { note: 'A corroborating note was captured.' } }],
                        },
                    ],
                }}
                onClose={jest.fn()}
            />
        )

        await userEvent.click(screen.getByText('Captured reports (1)'))
        expect(screen.getByText(label)).not.toBeNull()
        expect(screen.getByText('The original report summary.')).not.toBeNull()
        expect(screen.queryByText(/The latest check confirms/)).toBeNull()
        expect(screen.queryByText(/Delivery selection cleared/)).toBeNull()
        expect(screen.queryByText(/A corroborating note/)).toBeNull()

        await userEvent.click(screen.getByText('Changes made (1)'))
        expect(screen.getByText(/The latest check confirms the saved finding/)).not.toBeNull()
        await userEvent.click(screen.getByText('Captured data'))
        expect(screen.getByText(/"corroboration_only": true/)).not.toBeNull()
        await userEvent.click(screen.getByText('Evidence (1)'))
        expect(screen.getByText(/Delivery selection cleared after removing a coupon/)).not.toBeNull()
        await userEvent.click(screen.getByText('Report activity (1)'))
        expect(screen.getByText(/A corroborating note was captured/)).not.toBeNull()
    })
})
