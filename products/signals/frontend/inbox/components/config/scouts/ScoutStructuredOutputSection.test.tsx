import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutStructuredOutputSection } from './ScoutStructuredOutputSection'

const SCHEMA = {
    type: 'object',
    properties: { verdict: { enum: ['good', 'bad'] }, reason: { type: 'string' } },
    required: ['verdict'],
}

const CONFIG: SignalScoutConfigApi = {
    id: 'config-1',
    skill_name: 'signals-scout-hygiene',
    description: 'Dashboard hygiene',
    scout_origin: 'custom',
    scout_role: 'specialist',
    owners: [],
    enabled: true,
    status: 'active',
    pause_reason: null,
    deprecation: null,
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
    status_changed_by: null,
    auto_pause_exempt: false,
    network_access: 'trusted',
    model: null,
    tags: [],
    source_product: null,
    source_id: null,
    created_at: '2026-07-21T12:00:00Z',
    updated_at: '2026-07-21T12:00:00Z',
}

describe('ScoutStructuredOutputSection', () => {
    beforeEach(() => {
        initKeaTests()
    })
    afterEach(cleanup)

    const openSection = (config: SignalScoutConfigApi): jest.Mock => {
        const onUpdate = jest.fn()
        render(<ScoutStructuredOutputSection config={config} onUpdate={onUpdate} />)
        fireEvent.click(screen.getByText('Structured output'))
        return onUpdate
    }

    it.each([
        ['a live scout', true],
        // A dry-run scout records nothing, so a header that reads the same as a live scout's would
        // promise records the next run cannot write.
        ['a dry-run scout', false],
    ])('shows what the scout records without opening the section, for %s', (_name, emit) => {
        render(
            <ScoutStructuredOutputSection
                config={{ ...CONFIG, emit, structured_output_schema: SCHEMA }}
                onUpdate={jest.fn()}
            />
        )

        expect(screen.getByText('verdict')).toBeInTheDocument()
        expect(screen.queryByText('Off')).not.toBeInTheDocument()
        expect(screen.queryByText('Inactive during dry run') !== null).toBe(!emit)
    })

    it('stages an edit and saves the parsed schema only on the save button', () => {
        // The whole reason this section has a save button: the scout reads the schema verbatim in
        // its prompt, so a half-typed schema must not reach the next run.
        const onUpdate = openSection(CONFIG)
        const editor = screen.getByLabelText('signals-scout-hygiene record schema')

        fireEvent.change(editor, { target: { value: JSON.stringify(SCHEMA) } })
        expect(onUpdate).not.toHaveBeenCalled()

        fireEvent.click(screen.getByText('Save schema'))
        expect(onUpdate).toHaveBeenCalledWith('config-1', { structured_output_schema: SCHEMA })
    })

    it.each([
        // The typed JSON is the only copy of the edit, so a refused save must leave it to correct.
        ['refuses', null, JSON.stringify(SCHEMA)],
        ['accepts', SCHEMA, JSON.stringify(SCHEMA, null, 2)],
    ])('keeps the right text in the editor when the API %s the save', (_outcome, stored, expectedText) => {
        // Like scoutFleetLogic, the save patches the config and marks the scout as updating before the
        // request settles, and the settled config replaces the patch.
        let rerender: (ui: JSX.Element) => void = () => {}
        const onUpdate = (_configId: string, updates: Partial<SignalScoutConfigApi>): void =>
            rerender(<ScoutStructuredOutputSection config={{ ...CONFIG, ...updates }} onUpdate={jest.fn()} updating />)
        ;({ rerender } = render(<ScoutStructuredOutputSection config={CONFIG} onUpdate={onUpdate} />))
        fireEvent.click(screen.getByText('Structured output'))
        const editor = screen.getByLabelText('signals-scout-hygiene record schema')

        fireEvent.change(editor, { target: { value: JSON.stringify(SCHEMA) } })
        fireEvent.click(screen.getByText('Save schema'))
        rerender(
            <ScoutStructuredOutputSection
                config={{ ...CONFIG, structured_output_schema: stored }}
                onUpdate={jest.fn()}
            />
        )

        expect(editor).toHaveValue(expectedText)
    })

    it('refuses to save a schema the API would reject', () => {
        const onUpdate = openSection(CONFIG)

        fireEvent.change(screen.getByLabelText('signals-scout-hygiene record schema'), {
            target: { value: '{"type": "string"}' },
        })

        expect(screen.getByText('The schema must set "type": "object" at its root.')).toBeInTheDocument()
        fireEvent.click(screen.getByText('Save schema'))
        expect(onUpdate).not.toHaveBeenCalled()
    })

    it('turns the channel off only after the clear is confirmed', () => {
        // A stray click must not delete a schema the scout records against.
        const onUpdate = openSection({ ...CONFIG, structured_output_schema: SCHEMA })

        fireEvent.click(screen.getByText('Turn off'))
        expect(onUpdate).not.toHaveBeenCalled()

        fireEvent.click(screen.getByText('Turn off'))
        expect(onUpdate).toHaveBeenCalledWith('config-1', { structured_output_schema: null })
    })
})
