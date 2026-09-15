import '@testing-library/jest-dom'

import { type RenderResult, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'

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

function renderPickers(overrides: Partial<React.ComponentProps<typeof ComposerModelEffortPickers>> = {}): RenderResult {
    const result = render(
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
    return result
}

describe('ComposerModelEffortPickers', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        [undefined, 'gpt-5.6-sol'],
        ['gpt-5.6-luna', 'gpt-5.6-luna'],
    ])('waits for the default model %s before switching to Codex', async (defaultModel, expectedModel) => {
        const onModelChange = jest.fn()
        const props: React.ComponentProps<typeof ComposerModelEffortPickers> = {
            selectedModel: 'claude-sonnet-5',
            selectedEffort: ReasoningEffortEnumApi.Low,
            defaultModel,
            onModelChange,
            onEffortChange: jest.fn(),
            models: [
                ...CATALOGUE,
                ...['gpt-5.6-luna', 'gpt-5.6-sol'].map((model) => ({
                    runtime_adapter: RuntimeAdapterEnumApi.Codex,
                    model,
                    display_name: model,
                    supported_efforts: [ReasoningEffortEnumApi.High],
                })),
            ],
        }
        const { rerender } = renderPickers({ ...props, defaultModel: null, isDefaultModelLoading: true })

        fireEvent.click(screen.getByText('Harness'))
        const codexOption = await screen.findByText('Codex')
        expect(codexOption).toHaveAttribute('aria-disabled', 'true')
        fireEvent.click(codexOption)
        expect(onModelChange).not.toHaveBeenCalled()

        rerender(<ComposerModelEffortPickers {...props} isDefaultModelLoading={false} />)
        fireEvent.click(await screen.findByText('Codex'))

        expect(onModelChange).toHaveBeenCalledWith(expectedModel)
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
