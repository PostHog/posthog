import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

import {
    ModelChoiceApi,
    ReasoningEffortEnumApi,
    RuntimeAdapterEnumApi,
} from 'products/tasks/frontend/generated/api.schemas'

import { ComposerModelEffortPickers } from './ComposerModelEffortPickers'

const CATALOGUE: ModelChoiceApi[] = [
    {
        runtime_adapter: RuntimeAdapterEnumApi.Claude,
        model: 'claude-sonnet-5',
        display_name: 'Claude Sonnet 5',
        supported_efforts: [ReasoningEffortEnumApi.Low, ReasoningEffortEnumApi.Medium, ReasoningEffortEnumApi.High],
    },
    {
        runtime_adapter: RuntimeAdapterEnumApi.Claude,
        model: 'claude-opus-5',
        display_name: 'Claude Opus 5',
        supported_efforts: [ReasoningEffortEnumApi.Low, ReasoningEffortEnumApi.Medium, ReasoningEffortEnumApi.High],
    },
]

function renderPickers(overrides: Partial<React.ComponentProps<typeof ComposerModelEffortPickers>> = {}): void {
    render(
        <ComposerModelEffortPickers
            models={CATALOGUE}
            selectedModel="claude-opus-5"
            selectedEffort={ReasoningEffortEnumApi.High}
            onModelChange={jest.fn()}
            onEffortChange={jest.fn()}
            {...overrides}
        />
    )
    fireEvent.click(screen.getByRole('button'))
}

describe('ComposerModelEffortPickers', () => {
    afterEach(() => {
        cleanup()
    })

    it('offers no way to change the default on a surface that has none to change', () => {
        renderPickers()

        expect(screen.getByText('Reset to default')).toBeInTheDocument()
        expect(screen.queryByText('Change default')).not.toBeInTheDocument()
    })

    it('sends the user to where the default is configured', async () => {
        const onOpenDefaultSettings = jest.fn()
        renderPickers({ onOpenDefaultSettings })

        fireEvent.click(screen.getByText('Change default'))

        // Applied once the menu has finished closing, not on the click itself.
        await waitFor(() => expect(onOpenDefaultSettings).toHaveBeenCalledTimes(1))
    })
})
