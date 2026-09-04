import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutWriteAccessSection } from './ScoutWriteAccessSection'

const CONFIG: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: 'signals-scout-hygiene',
    description: 'Dashboard hygiene',
    scout_origin: 'custom',
    owners: [],
    enabled: true,
    status: 'active',
    pause_reason: null,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: null,
    output_destinations: {},
    structured_output_schema: null,
    mcp_gateway_server_ids: [],
    write_scopes: [],
    last_run_at: null,
    consecutive_failure_count: 0,
    status_changed_at: null,
    auto_pause_exempt: false,
    network_access: 'trusted',
    model: null,
    tags: [],
    source_product: null,
    source_id: null,
    created_at: '2026-07-21T12:00:00Z',
}

describe('ScoutWriteAccessSection', () => {
    beforeEach(() => {
        initKeaTests()
    })
    afterEach(cleanup)

    const openSection = (): jest.Mock => {
        const onUpdate = jest.fn()
        render(<ScoutWriteAccessSection config={CONFIG} onUpdate={onUpdate} />)
        fireEvent.click(screen.getByText('Write access'))
        return onUpdate
    }

    it('shows what the scout holds without opening the section', () => {
        render(
            <ScoutWriteAccessSection config={{ ...CONFIG, write_scopes: ['dashboard:write'] }} onUpdate={jest.fn()} />
        )

        expect(screen.getByText('Dashboards')).toBeInTheDocument()
        expect(screen.queryByText('Read only')).not.toBeInTheDocument()
    })

    it('stages a toggle and saves only on the save button', () => {
        // The whole reason this section has a save button: a stray click must not widen what an
        // unattended agent can change in the project.
        const onUpdate = openSection()

        fireEvent.click(screen.getByLabelText('Let this scout write dashboards'))
        expect(onUpdate).not.toHaveBeenCalled()

        fireEvent.click(screen.getByText('Save write access'))
        expect(onUpdate).toHaveBeenCalledWith('config-1', { write_scopes: ['dashboard:write'] })
    })
})
