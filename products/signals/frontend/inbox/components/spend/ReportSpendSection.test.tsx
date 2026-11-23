import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'

import * as api from 'products/signals/frontend/generated/api'
import type { ReportSpendApi } from 'products/signals/frontend/generated/api.schemas'

import { ReportSpendSection } from './ReportSpendSection'

describe('ReportSpendSection', () => {
    const amount = (total_spend: number | null): ReportSpendApi['generation'] => ({ total_spend, incomplete: false })

    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SELF_DRIVING_USAGE_DISPLAY], {
            [FEATURE_FLAGS.SELF_DRIVING_USAGE_DISPLAY]: true,
        })
    })

    afterEach(() => {
        cleanup()
        jest.restoreAllMocks()
    })

    test.each([
        {
            name: 'scout-authored report with a scout run receipt',
            scoutAuthored: true,
            scoutSpend: 1400,
            header: null,
            generationRow: false,
            notTracked: 0,
        },
        {
            name: 'scout-authored report without a scout run receipt',
            scoutAuthored: true,
            scoutSpend: null,
            header: null,
            generationRow: false,
            notTracked: 1,
        },
        {
            name: 'pipeline report without generation receipts',
            scoutAuthored: false,
            scoutSpend: null,
            header: 'Not tracked',
            generationRow: true,
            notTracked: 2,
        },
    ])('$name', async ({ scoutAuthored, scoutSpend, header, generationRow, notTracked }) => {
        jest.spyOn(api, 'signalsReportSpend').mockResolvedValue({
            generation: amount(null),
            implementation: amount(null),
            shared_scout_runs: amount(scoutSpend),
            scout_authored: scoutAuthored,
        })
        render(<ReportSpendSection reportId="report-1" />)

        await userEvent.click(screen.getByText('Usage'))
        await waitFor(() => expect(document.querySelector('[data-attr="report-spend"]')).toBeInTheDocument())

        expect(document.querySelector('[data-attr="report-spend-total"]')?.textContent ?? null).toBe(header)
        expect(screen.queryByText('Report generation') !== null).toBe(generationRow)
        expect(screen.queryAllByText('Not tracked')).toHaveLength(notTracked)
    })
})
