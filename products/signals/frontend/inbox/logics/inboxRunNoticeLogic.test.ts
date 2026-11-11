/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { runnerPanelLogic } from '~/layout/ai/runnerPanelLogic'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { makeReport } from '../__mocks__/inboxMocks'
import { REPORT_AI_PANEL_ID } from '../inboxTaskKickoffLogic'
import { inboxRunNoticeLogic } from './inboxRunNoticeLogic'

describe('inboxRunNoticeLogic', () => {
    let logic: ReturnType<typeof inboxRunNoticeLogic.build>
    const report = makeReport({ id: 'report-notice', title: 'Checkout fails on retry' })

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.INBOX_RUN_FINISHED_NOTICES], {
            [FEATURE_FLAGS.INBOX_RUN_FINISHED_NOTICES]: true,
        })
        logic = inboxRunNoticeLogic()
        logic.mount()
        jest.spyOn(lemonToast, 'success')
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it.each([
        {
            name: 'tells the person when the run finishes',
            status: 'completed',
            chatOnRun: false,
            toasts: 1,
            watched: 0,
        },
        {
            name: 'stays quiet when the chat already shows the run',
            status: 'completed',
            chatOnRun: true,
            toasts: 0,
            watched: 0,
        },
        {
            name: 'keeps watching a run that still works',
            status: 'in_progress',
            chatOnRun: false,
            toasts: 0,
            watched: 1,
        },
    ])('$name', async ({ status, chatOnRun, toasts, watched }) => {
        useMocks({ get: { '/api/projects/:team/tasks/:id/': { id: 'task-1', latest_run: { id: 'run-1', status } } } })
        logic.actions.openReportTask(report, 'task-1', 'run-1')
        if (!chatOnRun) {
            runnerPanelLogic({ panelId: REPORT_AI_PANEL_ID }).actions.clearActiveCreation()
        }

        await expectLogic(logic, () => logic.actions.pollWatchedRuns()).toFinishAllListeners()

        expect(lemonToast.success).toHaveBeenCalledTimes(toasts)
        expect(Object.keys(logic.values.watchedRuns)).toHaveLength(watched)
    })
})
