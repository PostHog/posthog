import type { LemonSelectOptions } from '@posthog/lemon-ui'

import type { WidgetGenerateRequestApi } from 'products/notebooks/frontend/generated/api.schemas'

export type WidgetModel = NonNullable<WidgetGenerateRequestApi['model']>

export const DEFAULT_WIDGET_MODEL: WidgetModel = 'claude-sonnet-4-6'
export const DEFAULT_WIDGET_PROMPT = 'Create an interactive visualization of the data in this notebook.'
export const MAX_WIDGET_PROMPT_LENGTH = 20_000
export const MAX_WIDGET_EFFECTIVE_PROMPT_LENGTH = 50_000

export type WidgetModelInfo = {
    name: string
    estimateLabel: string
    estimatedSeconds: number
}

export const WIDGET_MODEL_INFO: Record<WidgetModel, WidgetModelInfo> = {
    'claude-haiku-4-5': {
        name: 'Claude Haiku 4.5',
        estimateLabel: '~1 min',
        estimatedSeconds: 60,
    },
    'claude-sonnet-4-6': {
        name: 'Claude Sonnet 4.6',
        estimateLabel: '~2 min',
        estimatedSeconds: 120,
    },
    'claude-sonnet-5': {
        name: 'Claude Sonnet 5',
        estimateLabel: '~3 min',
        estimatedSeconds: 180,
    },
    'claude-opus-5': {
        name: 'Claude Opus 5',
        estimateLabel: '~5 min',
        estimatedSeconds: 300,
    },
}

export function isWidgetModel(model: string | null | undefined): model is WidgetModel {
    return model !== null && model !== undefined && model in WIDGET_MODEL_INFO
}

export const WIDGET_MODEL_OPTIONS: LemonSelectOptions<WidgetModel> = [
    {
        value: 'claude-haiku-4-5',
        label: `Fast - ${WIDGET_MODEL_INFO['claude-haiku-4-5'].name} (${WIDGET_MODEL_INFO['claude-haiku-4-5'].estimateLabel})`,
        tooltip: 'Returns simpler widgets more quickly.',
    },
    {
        value: 'claude-sonnet-4-6',
        label: `Balanced - ${WIDGET_MODEL_INFO['claude-sonnet-4-6'].name} (${WIDGET_MODEL_INFO['claude-sonnet-4-6'].estimateLabel})`,
        tooltip: 'Balances generation time and visual detail.',
    },
    {
        value: 'claude-sonnet-5',
        label: `High quality - ${WIDGET_MODEL_INFO['claude-sonnet-5'].name} (${WIDGET_MODEL_INFO['claude-sonnet-5'].estimateLabel})`,
        tooltip: 'Produces more detailed widgets and may take longer.',
    },
    {
        value: 'claude-opus-5',
        label: `Highest quality - ${WIDGET_MODEL_INFO['claude-opus-5'].name} (${WIDGET_MODEL_INFO['claude-opus-5'].estimateLabel})`,
        tooltip: 'Produces the most detailed widgets and may take the longest.',
    },
]
