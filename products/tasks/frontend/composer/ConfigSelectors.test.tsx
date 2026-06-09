import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import type { SessionConfigOption } from '../conversation/acp-types'
import { ModeSelector, ModelSelector, ReasoningEffortSelector } from './ConfigSelectors'

const modeOption: SessionConfigOption = {
    type: 'select',
    id: 'mode',
    name: 'Mode',
    category: 'mode',
    currentValue: 'default',
    options: [
        { value: 'plan', name: 'Plan' },
        { value: 'default', name: 'Default' },
        { value: 'acceptEdits', name: 'Accept edits' },
        { value: 'bypassPermissions', name: 'Bypass' },
    ],
}

const groupedModelOption: SessionConfigOption = {
    type: 'select',
    id: 'model',
    name: 'Model',
    category: 'model',
    currentValue: 'sonnet',
    options: [
        {
            group: 'claude',
            name: 'Claude',
            options: [
                { value: 'opus', name: 'Opus' },
                { value: 'sonnet', name: 'Sonnet' },
            ],
        },
        {
            group: 'codex',
            name: 'Codex',
            options: [{ value: 'gpt', name: 'GPT' }],
        },
    ],
}

const flatModelOption: SessionConfigOption = {
    type: 'select',
    id: 'model',
    name: 'Model',
    category: 'model',
    currentValue: 'sonnet',
    options: [
        { value: 'opus', name: 'Opus' },
        { value: 'sonnet', name: 'Sonnet' },
    ],
}

const thoughtOption: SessionConfigOption = {
    type: 'select',
    id: 'thought_level',
    name: 'Effort',
    category: 'thought_level',
    currentValue: 'high',
    options: [
        { value: 'low', name: 'Low', description: 'Faster' },
        { value: 'high', name: 'High' },
    ],
}

const booleanOption: SessionConfigOption = {
    type: 'boolean',
    id: 'flag',
    name: 'Flag',
    category: 'mode',
    currentValue: true,
}

describe('ConfigSelectors', () => {
    afterEach(() => {
        cleanup()
    })

    async function openMenu(): Promise<void> {
        await userEvent.click(screen.getByRole('button'))
    }

    describe('ModeSelector', () => {
        it('renders the label for the current value sourced from options', () => {
            render(<ModeSelector modeOption={modeOption} onChange={jest.fn()} />)
            expect(screen.getByRole('button')).toHaveTextContent('Default')
        })

        it('hides bypass modes by default', async () => {
            render(<ModeSelector modeOption={modeOption} onChange={jest.fn()} />)
            await openMenu()
            expect(screen.getByText('Plan')).toBeInTheDocument()
            expect(screen.getByText('Accept edits')).toBeInTheDocument()
            expect(screen.queryByText('Bypass')).not.toBeInTheDocument()
        })

        it('shows bypass modes when allowBypassPermissions is set', async () => {
            render(<ModeSelector modeOption={modeOption} onChange={jest.fn()} allowBypassPermissions />)
            await openMenu()
            expect(screen.getByText('Bypass')).toBeInTheDocument()
        })

        it('calls onChange with the selected value', async () => {
            const onChange = jest.fn()
            render(<ModeSelector modeOption={modeOption} onChange={onChange} />)
            await openMenu()
            await userEvent.click(screen.getByText('Accept edits'))
            expect(onChange).toHaveBeenCalledWith('acceptEdits')
        })

        it('returns null for a non-select option', () => {
            const { container } = render(<ModeSelector modeOption={booleanOption} onChange={jest.fn()} />)
            expect(container).toBeEmptyDOMElement()
        })

        it('returns null when the option is absent', () => {
            const { container } = render(<ModeSelector modeOption={undefined} onChange={jest.fn()} />)
            expect(container).toBeEmptyDOMElement()
        })

        it('falls back to currentValue when no matching option name exists', () => {
            render(
                <ModeSelector
                    modeOption={{ ...modeOption, currentValue: 'unknown' } as SessionConfigOption}
                    onChange={jest.fn()}
                />
            )
            expect(screen.getByRole('button')).toHaveTextContent('unknown')
        })
    })

    describe('ModelSelector', () => {
        it('flattens grouped options into a single list', async () => {
            render(<ModelSelector modelOption={groupedModelOption} onChange={jest.fn()} />)
            await openMenu()
            expect(screen.getByText('Opus')).toBeInTheDocument()
            // 'Sonnet' is the current value, so it appears in both the trigger and the menu.
            expect(screen.getAllByText('Sonnet').length).toBeGreaterThan(0)
            expect(screen.getByText('GPT')).toBeInTheDocument()
        })

        it('renders flat options unchanged', async () => {
            render(<ModelSelector modelOption={flatModelOption} onChange={jest.fn()} />)
            await openMenu()
            expect(screen.getByText('Opus')).toBeInTheDocument()
            // 'Sonnet' is the current value, so it appears in both the trigger and the menu.
            expect(screen.getAllByText('Sonnet').length).toBeGreaterThan(0)
        })

        it('labels the button with the current grouped value name', () => {
            render(<ModelSelector modelOption={groupedModelOption} onChange={jest.fn()} />)
            expect(screen.getByRole('button')).toHaveTextContent('Sonnet')
        })

        it('calls onChange with a value from inside a group', async () => {
            const onChange = jest.fn()
            render(<ModelSelector modelOption={groupedModelOption} onChange={onChange} />)
            await openMenu()
            await userEvent.click(screen.getByText('GPT'))
            expect(onChange).toHaveBeenCalledWith('gpt')
        })

        it('returns null when the option is absent', () => {
            const { container } = render(<ModelSelector modelOption={undefined} onChange={jest.fn()} />)
            expect(container).toBeEmptyDOMElement()
        })

        it('returns null when there are no options', () => {
            const { container } = render(
                <ModelSelector
                    modelOption={{ ...flatModelOption, options: [] } as SessionConfigOption}
                    onChange={jest.fn()}
                />
            )
            expect(container).toBeEmptyDOMElement()
        })
    })

    describe('ReasoningEffortSelector', () => {
        it('renders the value with the Effort prefix', () => {
            render(<ReasoningEffortSelector thoughtOption={thoughtOption} onChange={jest.fn()} />)
            expect(screen.getByRole('button')).toHaveTextContent('Effort: High')
        })

        it('calls onChange with the selected value', async () => {
            const onChange = jest.fn()
            render(<ReasoningEffortSelector thoughtOption={thoughtOption} onChange={onChange} />)
            await openMenu()
            await userEvent.click(screen.getByText('Low'))
            expect(onChange).toHaveBeenCalledWith('low')
        })

        it('returns null when the option is absent', () => {
            const { container } = render(<ReasoningEffortSelector thoughtOption={undefined} onChange={jest.fn()} />)
            expect(container).toBeEmptyDOMElement()
        })
    })
})
