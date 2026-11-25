import type { ModelChoiceApi } from '@/api/tasks'

export const DEMO_COST_BASELINE = 'Claude Sonnet 5'

export const DEMO_MODEL_CATALOGUE: ModelChoiceApi[] = [
    {
        runtime_adapter: 'claude',
        model: 'claude-opus-5-5',
        display_name: 'Claude Opus 5.5',
        supported_efforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'],
        cost_multiplier: '2×',
        offered: true,
    },
    {
        runtime_adapter: 'claude',
        model: 'claude-sonnet-5-5',
        display_name: 'Claude Sonnet 5.5',
        supported_efforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'],
        cost_multiplier: '1×',
        offered: true,
    },
    {
        runtime_adapter: 'claude',
        model: 'claude-fable-5-1',
        display_name: 'Claude Fable 5.1',
        supported_efforts: ['low', 'medium', 'high', 'xhigh', 'max', 'ultracode'],
        cost_multiplier: '5×',
        offered: true,
    },
    {
        runtime_adapter: 'claude',
        model: 'moonshotai/kimi-k3',
        display_name: 'Kimi K3',
        supported_efforts: [],
        cost_multiplier: '1.5×',
        offered: true,
    },
    {
        runtime_adapter: 'codex',
        model: 'gpt-6.1-sol',
        display_name: 'GPT-6.1 Sol',
        supported_efforts: ['low', 'medium', 'high', 'xhigh', 'max'],
        cost_multiplier: '1× base',
        offered: true,
    },
    {
        runtime_adapter: 'codex',
        model: 'gpt-6-luna',
        display_name: 'GPT-6 Luna',
        supported_efforts: ['low', 'medium', 'high', 'xhigh', 'max'],
        cost_multiplier: '0.05×',
        offered: true,
    },
]
