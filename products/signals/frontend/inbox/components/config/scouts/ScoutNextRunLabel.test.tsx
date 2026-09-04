import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutNextRunLabel } from './ScoutNextRunLabel'

// TZLabel shares a 1-second ticker between its instances, so the 30-day case below would run
// millions of interval callbacks against the real component.
jest.mock('lib/components/TZLabel', () => ({
    TZLabel: ({ time }: { time: string }) => <span>{time}</span>,
}))

const NOW = new Date('2026-07-21T12:00:00Z')
const MINUTE_MS = 60 * 1000

const config: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: 'signals-scout-general',
    description: 'General scout',
    scout_origin: 'canonical',
    owners: [],
    enabled: true,
    status: 'active',
    pause_reason: null,
    emit: true,
    run_interval_minutes: 30,
    run_cron_schedule: null,
    output_destinations: {},
    structured_output_schema: null,
    mcp_gateway_server_ids: [],
    last_run_at: '2026-07-21T11:50:00Z',
    consecutive_failure_count: 0,
    status_changed_at: null,
    auto_pause_exempt: false,
    network_access: 'trusted',
    model: null,
    tags: [],
    source_product: null,
    source_id: null,
    created_at: '2026-07-21T00:00:00Z',
}

describe('ScoutNextRunLabel', () => {
    beforeEach(() => {
        jest.useFakeTimers({ now: NOW })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
        jest.useRealTimers()
    })

    it('turns over to "Due now" as the run falls due, with no reload', () => {
        // Surfaces that do not poll never re-render this label on their own, so without its own
        // wake-up an open tab keeps showing a time that has already passed as the next run.
        render(<ScoutNextRunLabel config={config} />)

        expect(screen.queryByText('Due now')).not.toBeInTheDocument()

        act(() => {
            jest.advanceTimersByTime(20 * MINUTE_MS)
        })

        expect(screen.getByText('Due now')).toBeInTheDocument()
    })

    it('still turns over when the run is further off than one timer reaches', () => {
        const intervalMinutes = 30 * 24 * 60
        // `last_run_at` sits 10 minutes before `NOW`, so the run falls that much short of a full
        // interval away. setTimeout tops out near 24.9 days, short of both.
        const dueInMinutes = intervalMinutes - 10
        const pastOneTimerMinutes = 25 * 24 * 60

        render(<ScoutNextRunLabel config={{ ...config, run_interval_minutes: intervalMinutes }} />)

        act(() => {
            jest.advanceTimersByTime(pastOneTimerMinutes * MINUTE_MS)
        })

        expect(screen.queryByText('Due now')).not.toBeInTheDocument()

        act(() => {
            jest.advanceTimersByTime((dueInMinutes - pastOneTimerMinutes) * MINUTE_MS)
        })

        expect(screen.getByText('Due now')).toBeInTheDocument()
    })
})
