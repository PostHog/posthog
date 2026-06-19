import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { signalsReportsLinkedReportsRetrieve } from '../../../../../signals/frontend/generated/api'
import type { ErrorTrackingLinkedReportApi } from '../../../../../signals/frontend/generated/api.schemas'
import { relatedInboxReportsLogic } from './relatedInboxReportsLogic'

jest.mock('../../../../../signals/frontend/generated/api', () => ({
    signalsReportsLinkedReportsRetrieve: jest.fn(),
}))

const mockRetrieve = signalsReportsLinkedReportsRetrieve as jest.MockedFunction<
    typeof signalsReportsLinkedReportsRetrieve
>

const ISSUE_ID = 'issue-abc'

const baseReport: ErrorTrackingLinkedReportApi = {
    id: 'report-1',
    title: 'Crash on save',
    status: 'ready',
    created_at: '2026-01-15T00:00:00Z',
    implementation_pr_url: null,
}

describe('relatedInboxReportsLogic', () => {
    let logic: ReturnType<typeof relatedInboxReportsLogic.build>

    beforeEach(() => {
        initKeaTests()
        jest.resetAllMocks()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('lazily loads linked reports on mount with the error_tracking source product', async () => {
        mockRetrieve.mockResolvedValue([baseReport])
        logic = relatedInboxReportsLogic({ issueId: ISSUE_ID })
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                relatedReports: [baseReport],
            })
        expect(mockRetrieve).toHaveBeenCalledWith(String(MOCK_DEFAULT_TEAM.id), {
            source_product: 'error_tracking',
            source_id: ISSUE_ID,
        })
    })

    it('exposes the implementation PR url when present', async () => {
        const reportWithPr: ErrorTrackingLinkedReportApi = {
            ...baseReport,
            implementation_pr_url: 'https://github.com/org/repo/pull/7',
        }
        mockRetrieve.mockResolvedValue([reportWithPr])
        logic = relatedInboxReportsLogic({ issueId: ISSUE_ID })
        logic.mount()

        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({
                relatedReports: [reportWithPr],
            })
    })

    it('defaults to an empty list when nothing is linked', async () => {
        mockRetrieve.mockResolvedValue([])
        logic = relatedInboxReportsLogic({ issueId: ISSUE_ID })
        logic.mount()

        await expectLogic(logic).toFinishAllListeners().toMatchValues({
            relatedReports: [],
        })
    })
})
