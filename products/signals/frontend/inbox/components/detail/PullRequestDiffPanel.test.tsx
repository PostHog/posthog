import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { CommitDiffResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { makeReport } from '../../__mocks__/inboxMocks'
import { inboxReportDetailLogic } from '../../logics/inboxReportDetailLogic'
import { CommitContent } from './artefactTypes'
import { PullRequestDiffStat } from './PullRequestDiffPanel'
import { summarizeDiff } from './PullRequestDiffView'
import { PullRequestFilesChanged } from './PullRequestFilesChanged'

jest.mock('@pierre/diffs', () => ({ parsePatchFiles: jest.fn() }), { virtual: true })
jest.mock('@pierre/diffs/react', () => ({ FileDiff: () => null }), { virtual: true })

const commit: CommitContent = {
    repository: 'example/app',
    branch: 'fix-diff',
    commit_sha: 'abc123',
    message: 'Fix diff',
}

describe('PullRequestDiffPanel', () => {
    afterEach(cleanup)

    it.each([undefined, null, 42, {}])('returns no summary for a non-string diff: %p', (diff) => {
        expect(summarizeDiff(diff)).toBeNull()
    })

    it.each([{}, { diff: null }, { diff: 42 }, null])(
        'shows a load error instead of crashing for an invalid diff response: %p',
        async (response) => {
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/reports/:id/feedback_state/': { sentiment: null, note: '' },
                    '/api/projects/:team_id/signals/reports/:id/artefacts/': { results: [] },
                    '/api/projects/:team_id/signals/reports/:id/signals/': { signals: [] },
                    '/api/projects/:team_id/signals/reports/:id/checks/': { results: [] },
                    '/api/projects/:team_id/signals/reports/available_reviewers/': [],
                    '/api/projects/:team_id/signals/reports/:id/artefacts/:artefact_id/diff/': () => [200, response],
                },
            })
            initKeaTests()
            const report = makeReport()
            const logic = inboxReportDetailLogic({ reportId: report.id, report })
            logic.mount()
            silenceKeaLoadersErrors()
            try {
                if (response !== null) {
                    logic.actions.loadReportDiffSuccess(response as unknown as CommitDiffResponseApi)
                    const stat = render(<PullRequestDiffStat report={report} commit={commit} />)
                    expect(stat.container).toBeEmptyDOMElement()
                    stat.unmount()
                    logic.actions.loadReportDiffSuccess(null)
                }
                await expectLogic(logic, () => logic.actions.loadReportDiff({ artefactId: 'commit-1' }))
                    .toDispatchActions(['loadReportDiffFailure'])
                    .toMatchValues({ reportDiff: null, reportDiffLoading: false })

                const stat = render(<PullRequestDiffStat report={report} commit={commit} />)
                expect(stat.container).toBeEmptyDOMElement()
                render(<PullRequestFilesChanged report={report} commit={commit} />)
                expect(
                    screen.getByText("Couldn't load the diff. Try again, or open the pull request on GitHub.")
                ).toBeInTheDocument()
            } finally {
                cleanup()
                logic.unmount()
                resumeKeaLoadersErrors()
            }
        }
    )

    it.each(['', ' \n'])('keeps an empty diff distinct from an invalid diff: %p', (diff) => {
        expect(summarizeDiff(diff)).toEqual({ fileCount: 0, additions: 0, deletions: 0 })
    })
})
