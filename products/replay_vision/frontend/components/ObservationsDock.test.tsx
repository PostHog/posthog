import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { VisionQuotaApi } from '../generated/api.schemas'
import { visionQuotaLogic } from '../logics/visionQuotaLogic'
import { notifyScanQuotaBlocked } from '../utils/quotaBlockedToast'
import { ScannerPicker } from './ObservationsDock'

jest.mock('../utils/quotaBlockedToast', () => ({ notifyScanQuotaBlocked: jest.fn() }))

const TRIGGER = '[data-attr="vision-scan-recording"]'

const quota = (exhausted: boolean): VisionQuotaApi => ({
    credit_limit: 1000,
    credits_used: exhausted ? 1000 : 100,
    remaining: exhausted ? 0 : 900,
    exhausted,
    period_start: '2026-08-01T00:00:00Z',
    period_end: '2026-09-01T00:00:00Z',
    projected_monthly_credits: 0,
    free_monthly_credits: 0,
})

describe('ScannerPicker', () => {
    let exhausted: boolean

    beforeEach(() => {
        useMocks({
            get: {
                '/api/projects/:team/vision/quota/': () => [200, quota(exhausted)],
                '/api/projects/:team/vision/scanners/': () => [200, { results: [] }],
                '/api/projects/:team/vision/observations/': () => [200, { results: [] }],
                '/api/billing/': () => [200, {}],
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.clearAllMocks()
    })

    // The exhausted trigger can't lean on `disabledReason` — LemonButton would swallow the click behind a
    // hover-only tooltip, which is exactly the dead-click users hit. A click must produce feedback instead.
    it('surfaces the quota block on click when exhausted', async () => {
        exhausted = true
        const { container } = render(
            <Provider>
                <ScannerPicker sessionId="sess-1" />
            </Provider>
        )
        await waitFor(() => expect(visionQuotaLogic.findMounted()?.values.quota?.exhausted).toBe(true))

        fireEvent.click(container.querySelector(TRIGGER)!)

        expect(notifyScanQuotaBlocked).toHaveBeenCalledTimes(1)
    })

    it('opens the picker without a quota toast when credits remain', async () => {
        exhausted = false
        const { container } = render(
            <Provider>
                <ScannerPicker sessionId="sess-1" />
            </Provider>
        )
        await waitFor(() => expect(visionQuotaLogic.findMounted()?.values.quota?.exhausted).toBe(false))

        fireEvent.click(container.querySelector(TRIGGER)!)

        expect(notifyScanQuotaBlocked).not.toHaveBeenCalled()
    })
})
