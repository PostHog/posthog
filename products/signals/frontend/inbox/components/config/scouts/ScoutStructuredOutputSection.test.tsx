import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen } from '@testing-library/react'

import { LemonDialog } from '@posthog/lemon-ui'

import { initKeaTests } from '~/test/init'

import type { SignalScoutConfigApi } from 'products/signals/frontend/generated/api.schemas'

import { mockScoutConfigs } from '../../../__mocks__/scoutConfigs'
import { ScoutStructuredOutputSection } from './ScoutStructuredOutputSection'

const SCHEMA = {
    type: 'object',
    properties: { verdict: { enum: ['good', 'bad'] }, reason: { type: 'string' } },
    required: ['verdict'],
}

// Built from the shared mock so a new required config field only needs adding in one place.
const CONFIG: SignalScoutConfigApi = {
    ...mockScoutConfigs[0],
    id: 'config-1',
    skill_name: 'signals-scout-hygiene',
    scout_origin: 'custom',
    enabled: true,
    emit: true,
    structured_output_schema: null,
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

    it.each([
        ['refuses', SCHEMA, '{"type": "object", "properties": {"score": {"type": "integer"}}}'],
        ['accepts', null, ''],
    ])('keeps the right text in the editor when the API %s the turn-off', (_outcome, stored, expectedText) => {
        const edit = '{"type": "object", "properties": {"score": {"type": "integer"}}}'
        const open = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        const withSchema = { ...CONFIG, structured_output_schema: SCHEMA }
        let rerender: (ui: JSX.Element) => void = () => {}
        const onUpdate = (_configId: string, updates: Partial<SignalScoutConfigApi>): void =>
            rerender(
                <ScoutStructuredOutputSection config={{ ...withSchema, ...updates }} onUpdate={jest.fn()} updating />
            )
        ;({ rerender } = render(<ScoutStructuredOutputSection config={withSchema} onUpdate={onUpdate} />))
        fireEvent.click(screen.getByText('Structured output'))
        const editor = screen.getByLabelText('signals-scout-hygiene record schema')

        fireEvent.change(editor, { target: { value: edit } })
        fireEvent.click(screen.getByText('Turn off'))
        act(() => open.mock.calls[0][0].primaryButton?.onClick?.({} as React.MouseEvent<HTMLElement>))
        rerender(
            <ScoutStructuredOutputSection
                config={{ ...CONFIG, structured_output_schema: stored }}
                onUpdate={jest.fn()}
            />
        )

        expect(editor).toHaveValue(expectedText)
        open.mockRestore()
    })

    it.each([
        // Half-typed JSON parses to no schema, which must not read as matching "no schema saved".
        ['a draft that does not parse yet', '{'],
        ['a valid draft', JSON.stringify(SCHEMA)],
    ])('reports %s as unsaved so the modal keeps it', (_name, text) => {
        const onUnsavedChange = jest.fn()
        render(<ScoutStructuredOutputSection config={CONFIG} onUpdate={jest.fn()} onUnsavedChange={onUnsavedChange} />)
        fireEvent.click(screen.getByText('Structured output'))

        fireEvent.change(screen.getByLabelText('signals-scout-hygiene record schema'), { target: { value: text } })

        expect(onUnsavedChange).toHaveBeenLastCalledWith(true)
    })

    it('refuses to save a schema the API would reject', () => {
        const onUpdate = openSection(CONFIG)

        fireEvent.change(screen.getByLabelText('signals-scout-hygiene record schema'), {
            target: { value: '{"type": "string"}' },
        })

        expect(screen.getByText('The schema must set "type": "object" at its root.')).toBeInTheDocument()
        expect(screen.getByLabelText('signals-scout-hygiene record schema')).toHaveAttribute('aria-invalid', 'true')
        fireEvent.click(screen.getByText('Save schema'))
        expect(onUpdate).not.toHaveBeenCalled()
    })

    it('turns the channel off only after the dialog is confirmed', () => {
        // A stray click must not delete a schema the scout records against.
        const open = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
        const onUpdate = openSection({ ...CONFIG, structured_output_schema: SCHEMA })

        fireEvent.click(screen.getByText('Turn off'))
        expect(onUpdate).not.toHaveBeenCalled()

        open.mock.calls[0][0].primaryButton?.onClick?.({} as React.MouseEvent<HTMLElement>)
        expect(onUpdate).toHaveBeenCalledWith('config-1', { structured_output_schema: null })
        open.mockRestore()
    })
})
