import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { ApiError } from 'lib/api-error'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { initKeaTests } from '~/test/init'

import { aeoPromptsWeeklyReport } from '../generated/api'
import type { AEOWeeklyReportApi } from '../generated/api.schemas'
import {
    WEEKLY_REPORT_SUBSCRIPTION_TITLE,
    contentAutopilotWeeklyReportLogic,
} from './contentAutopilotWeeklyReportLogic'

jest.mock('../generated/api', () => ({ aeoPromptsWeeklyReport: jest.fn() }))

const REPORT = { scorecard: { answers: 3 }, topics: [], pages: [], actions: [] } as unknown as AEOWeeklyReportApi

describe('contentAutopilotWeeklyReportLogic', () => {
    let logic: ReturnType<typeof contentAutopilotWeeklyReportLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        logic = contentAutopilotWeeklyReportLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it.each([
        ['loads the report', () => Promise.resolve(REPORT), REPORT, null],
        [
            'marks a missing rollout as forbidden',
            () => Promise.reject(new ApiError('Forbidden', 403)),
            null,
            'forbidden',
        ],
    ])('%s when the preview opens', async (_, response, expectedReport, expectedError) => {
        jest.mocked(aeoPromptsWeeklyReport).mockImplementation(response as () => Promise<AEOWeeklyReportApi>)
        silenceKeaLoadersErrors()
        await expectLogic(logic, () => logic.actions.openWeeklyReportPreview())
            .toFinishAllListeners()
            .toMatchValues({
                weeklyReportPreviewOpen: true,
                weeklyReport: expectedReport,
                weeklyReportError: expectedError,
            })
        resumeKeaLoadersErrors()
    })

    it('opens the subscription flow prefilled with the weekly report', async () => {
        logic.actions.openWeeklyReportPreview()
        await expectLogic(logic, () => logic.actions.sendWeeklyReport('preview')).toMatchValues({
            weeklyReportPreviewOpen: false,
        })

        expect(router.values.location.pathname).toContain(urls.subscriptionNew())
        expect(router.values.searchParams).toEqual({
            resource_type: 'ai_visibility_report',
            frequency: 'weekly',
            title: WEEKLY_REPORT_SUBSCRIPTION_TITLE,
        })
    })
})
