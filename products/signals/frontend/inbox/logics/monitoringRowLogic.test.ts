/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper. */
import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalReportCheckApi } from '../../generated/api.schemas'
import { monitoringRowLogic } from './monitoringRowLogic'

const CHECKS_URL = '/api/projects/:team_id/signals/reports/:report_id/checks/'

const check = (id: string): SignalReportCheckApi =>
    ({ id, kind: 'metric_threshold', status: 'active', config: {} }) as SignalReportCheckApi

describe('monitoringRowLogic', () => {
    beforeEach(() => {
        initKeaTests()
        silenceKeaLoadersErrors()
    })

    afterEach(() => resumeKeaLoadersErrors())

    it('loads checks when an already mounted row gains a lead check', async () => {
        let requestCount = 0
        useMocks({
            get: {
                [CHECKS_URL]: () => {
                    requestCount += 1
                    return [200, { results: [check('lead')] }]
                },
            },
        })
        const logic = monitoringRowLogic({ reportId: 'report', loadChecks: false })
        logic.mount()
        await Promise.resolve()
        expect(requestCount).toBe(0)

        monitoringRowLogic({ reportId: 'report', loadChecks: true })

        await waitFor(() => expect(logic.values.reportChecks?.[0]?.id).toBe('lead'))
        expect(requestCount).toBe(1)
        logic.unmount()
    })

    it.each([
        ['success', 200, { results: [check('older')] }],
        ['failure', 500, { detail: 'older request failed' }],
    ])('discards a stale %s after the row is reopened', async (_, status, body) => {
        let requestCount = 0
        let releaseFirst: () => void = () => {}
        useMocks({
            get: {
                [CHECKS_URL]: async () => {
                    requestCount += 1
                    if (requestCount === 1) {
                        await new Promise<void>((resolve) => (releaseFirst = resolve))
                        return [status, body]
                    }
                    return [200, { results: [check('newer')] }]
                },
            },
        })
        const first = monitoringRowLogic({ reportId: 'report', loadChecks: true })
        first.mount()
        await waitFor(() => expect(requestCount).toBe(1))
        first.unmount()

        const reopened = monitoringRowLogic({ reportId: 'report', loadChecks: true })
        reopened.mount()
        await waitFor(() => expect(reopened.values.reportChecks?.[0]?.id).toBe('newer'))

        releaseFirst()
        await expectLogic(first).toFinishAllListeners()

        expect(reopened.values.reportChecks?.[0]?.id).toBe('newer')
        expect(reopened.values.reportChecksLoadFailed).toBe(false)
        reopened.unmount()
    })
})
