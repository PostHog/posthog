import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutConfigForm } from './ScoutConfigControls'

const config: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: 'signals-scout-general',
    description: 'General scout',
    scout_origin: 'canonical',
    enabled: true,
    status: 'active',
    pause_reason: null,
    emit: true,
    run_interval_minutes: 1440,
    run_cron_schedule: '0 9 * * *',
    output_destinations: {},
    structured_output_schema: null,
    mcp_gateway_server_ids: [],
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

describe('ScoutConfigForm', () => {
    useMocks({
        get: {
            '/api/environments/:team_id/integrations/': () => [200, { results: [] }],
        },
    })

    beforeEach(() => initKeaTests())
    afterEach(cleanup)

    it('updates enablement and inbox emission from the settings form', () => {
        const onUpdate = jest.fn()
        const { getByText } = render(<ScoutConfigForm config={config} onUpdate={onUpdate} />)

        fireEvent.click(getByText('Enable this scout'))
        fireEvent.click(getByText('Write signals to the inbox'))

        expect(onUpdate).toHaveBeenNthCalledWith(1, 'config-1', { enabled: false })
        expect(onUpdate).toHaveBeenNthCalledWith(2, 'config-1', { emit: false })
        expect(getByText('Turn off inbox signals to run the scout in dry-run mode.')).toBeTruthy()
    })

    it('reflects the saved run settings and locks them while updating', () => {
        const onUpdate = jest.fn()
        const { getByRole } = render(
            <ScoutConfigForm config={{ ...config, emit: false }} onUpdate={onUpdate} updating />
        )

        const enabledSwitch = getByRole('switch', { name: 'Enable this scout' })
        const emitSwitch = getByRole('switch', { name: 'Write signals to the inbox' })

        expect(enabledSwitch).toHaveAttribute('aria-checked', 'true')
        expect(emitSwitch).toHaveAttribute('aria-checked', 'false')
        expect(enabledSwitch).toBeDisabled()
        expect(emitSwitch).toBeDisabled()
    })

    it('saves the daily run time on blur and never clears the schedule from an empty input', () => {
        const onUpdate = jest.fn()
        const { container, unmount } = render(<ScoutConfigForm config={config} onUpdate={onUpdate} />)
        const input = container.querySelector<HTMLInputElement>('input[type="time"]')

        expect(input).not.toBeNull()

        fireEvent.change(input!, { target: { value: '14:45' } })
        expect(onUpdate).not.toHaveBeenCalled()

        fireEvent.blur(input!)
        expect(onUpdate).toHaveBeenCalledWith('config-1', { run_cron_schedule: '45 14 * * *' })

        // A half-typed edit blurring empty must not silently revert the scout to its rolling
        // interval — switching schedule mode is the select's job.
        fireEvent.change(input!, { target: { value: '' } })
        fireEvent.blur(input!)
        expect(onUpdate).toHaveBeenCalledTimes(1)
        unmount()
    })

    it('shows an unexpressible cron as a read-only custom mode without a time picker', () => {
        const onUpdate = jest.fn()
        const { container, getByText, unmount } = render(
            <ScoutConfigForm config={{ ...config, run_cron_schedule: '0 9 * * 1-5' }} onUpdate={onUpdate} />
        )

        expect(container.querySelector('input[type="time"]')).toBeNull()
        expect(getByText('Custom (0 9 * * 1-5)')).toBeTruthy()
        unmount()
    })

    it('adds normalized tags as a full replacement set', () => {
        const onUpdate = jest.fn()
        const { getByLabelText, unmount } = render(
            <ScoutConfigForm config={{ ...config, tags: ['on-call'] }} onUpdate={onUpdate} />
        )
        const input = getByLabelText(`${config.skill_name} tags`)

        fireEvent.change(input, { target: { value: 'Revenue' } })
        fireEvent.keyDown(input, { key: 'Enter' })

        expect(onUpdate).toHaveBeenCalledWith('config-1', { tags: ['on-call', 'revenue'] })
        unmount()
    })
})
