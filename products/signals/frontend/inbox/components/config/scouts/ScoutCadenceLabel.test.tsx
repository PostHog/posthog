import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutCadenceLabel } from './ScoutCadenceLabel'

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
    run_interval_minutes: 1440,
    run_cron_schedule: '0 9 * * *',
    output_destinations: {},
    structured_output_schema: null,
    mcp_gateway_server_ids: [],
    last_run_at: '2026-07-21T08:00:00Z',
    consecutive_failure_count: 0,
    status_changed_at: null,
    auto_pause_exempt: false,
    network_access: 'trusted',
    model: null,
    tags: [],
    source_product: null,
    source_id: null,
    created_at: '2026-07-21T00:00:00Z',
    write_scopes: [],
}

describe('ScoutCadenceLabel', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    // The roster card is one big link to the scout. The hint's tooltip renders in a portal that
    // React still treats as part of this subtree, so a lost guard sends the click to that link and
    // the settings tab never opens.
    it('keeps the timezone settings link from reaching a surrounding link', async () => {
        const onSurroundingClick = jest.fn()
        render(
            <div onClick={onSurroundingClick}>
                <ScoutCadenceLabel config={config} />
            </div>
        )

        await userEvent.hover(await screen.findByText('(UTC)'))
        await userEvent.click(await screen.findByText("project's timezone", undefined, { timeout: 5000 }))

        expect(onSurroundingClick).not.toHaveBeenCalled()
    })
})
