import '@testing-library/jest-dom'

import { cleanup, fireEvent, render } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutConfigForm } from './ScoutConfigControls'

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

    beforeEach(() => {
        // featureFlagLogic persists to localStorage, which jsdom keeps across tests — without
        // clearing, a flag set in one test leaks into the next test's mount-time state.
        localStorage.clear()
        initKeaTests()
    })
    afterEach(cleanup)

    const emitSwitchLabel = 'signals-scout-general write signals to the inbox'

    it.each([
        ['live', true, false],
        ['dry run', false, true],
    ])('moves a %s scout to the other posture', (_posture, emit, expectedPatch) => {
        const onUpdate = jest.fn()
        const { getByLabelText } = render(<ScoutConfigForm config={{ ...config, emit }} onUpdate={onUpdate} />)

        const emitSwitch = getByLabelText(emitSwitchLabel)
        expect(emitSwitch).toHaveAttribute('aria-checked', String(emit))

        fireEvent.click(emitSwitch)

        expect(onUpdate).toHaveBeenCalledWith('config-1', { emit: expectedPatch })
    })

    // Settable while the scout is off, so a dry-run posture can be chosen before the enable
    // sends the first run out.
    it('leaves the dry-run switch editable while the scout is disabled', () => {
        const onUpdate = jest.fn()
        const { getByLabelText } = render(
            <ScoutConfigForm config={{ ...config, enabled: false }} onUpdate={onUpdate} />
        )

        expect(getByLabelText(emitSwitchLabel)).not.toBeDisabled()
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

    it('saves a weekly run day and keeps the run time', () => {
        const onUpdate = jest.fn()
        const { getByLabelText, getByText, container, unmount } = render(
            <ScoutConfigForm config={{ ...config, run_cron_schedule: '30 8 * * 1' }} onUpdate={onUpdate} />
        )

        expect(container.querySelector<HTMLInputElement>('input[type="time"]')?.value).toBe('08:30')

        fireEvent.click(getByLabelText('signals-scout-general run day'))
        fireEvent.click(getByText('Thursday'))
        expect(onUpdate).toHaveBeenCalledWith('config-1', { run_cron_schedule: '30 8 * * 4' })
        unmount()
    })

    it('edits a day-restricted cron in place and refuses one the scheduler would reject', () => {
        const onUpdate = jest.fn()
        const { getByLabelText, getByText, unmount } = render(
            <ScoutConfigForm config={{ ...config, run_cron_schedule: '0 9 1 2 *' }} onUpdate={onUpdate} />
        )
        const input = getByLabelText('signals-scout-general cron expression')

        fireEvent.change(input, { target: { value: '0,15 9 * * *' } })
        fireEvent.blur(input)
        expect(getByText('Runs must be at least 30 minutes apart.')).toBeTruthy()
        expect(onUpdate).not.toHaveBeenCalled()

        fireEvent.change(input, { target: { value: '0 9 * * 1-5' } })
        fireEvent.blur(input)
        expect(onUpdate).toHaveBeenCalledWith('config-1', { run_cron_schedule: '0 9 * * 1-5' })
        unmount()
    })

    // Guards the pin's wire values: a model option must patch the raw model id (not its display
    // label), and Default must patch null (not '') — the backend treats null as "clear the pin".
    it('pins a model from the dropdown and clears the pin via Default', () => {
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.SCOUTS_MODEL_CONFIG], {
            [FEATURE_FLAGS.SCOUTS_MODEL_CONFIG]: true,
        })
        const onUpdate = jest.fn()
        const modelSelectLabel = 'signals-scout-general model'
        const { getByLabelText, getByText, rerender, unmount } = render(
            <ScoutConfigForm config={config} onUpdate={onUpdate} />
        )

        fireEvent.click(getByLabelText(modelSelectLabel))
        fireEvent.click(getByText('GPT-5.6 Luna'))
        expect(onUpdate).toHaveBeenCalledWith('config-1', { model: 'gpt-5.6-luna' })

        rerender(<ScoutConfigForm config={{ ...config, model: 'gpt-5.6-luna' }} onUpdate={onUpdate} />)
        fireEvent.click(getByLabelText(modelSelectLabel))
        fireEvent.click(getByText('Default'))
        expect(onUpdate).toHaveBeenLastCalledWith('config-1', { model: null })
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
