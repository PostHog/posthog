import '@testing-library/jest-dom'

import { act, cleanup, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutNextRunLabel } from './ScoutNextRunLabel'

const NOW = new Date('2026-07-21T12:00:00Z')

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
            jest.advanceTimersByTime(20 * 60 * 1000)
        })

        expect(screen.getByText('Due now')).toBeInTheDocument()
    })
})
