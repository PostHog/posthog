import { ApiConfig } from '~/lib/api'

import type {
    BooleanScoreDefinitionConfigApi as BooleanScoreDefinitionConfig,
    CategoricalScoreDefinitionConfigApi as CategoricalScoreDefinitionConfig,
    CategoricalScoreOptionApi as ScoreDefinitionOption,
    ExperimentMetricKindEnumApi as ScoreDefinitionKind,
    NumericScoreDefinitionConfigApi as NumericScoreDefinitionConfig,
    ScoreDefinitionApi as ScoreDefinition,
    ScoreDefinitionConfigApi as ScoreDefinitionConfig,
} from '../generated/api.schemas'
import { getBooleanConfig, getCategoricalConfig, getNumericConfig } from './scoreDefinitionConfigUtils'

export type ScoreDefinitionModalMode = 'create' | 'duplicate' | 'metadata' | 'config'
export type CategoricalSelectionMode = 'single' | 'multiple'

export interface ScoreDefinitionDraft {
    name: string
    description: string
    kind: ScoreDefinitionKind
    options: ScoreDefinitionOption[]
    selectionMode: CategoricalSelectionMode
    categoricalMinSelections: string
    categoricalMaxSelections: string
    numericMin: string
    numericMax: string
    numericStep: string
    trueLabel: string
    falseLabel: string
}

export const CATEGORICAL_SELECTION_MODE_OPTIONS: { label: string; value: CategoricalSelectionMode }[] = [
    { label: 'Single select', value: 'single' },
    { label: 'Multi-select', value: 'multiple' },
]

const DEFAULT_BOOLEAN_TRUE_LABEL = 'Good'
const DEFAULT_BOOLEAN_FALSE_LABEL = 'Bad'

export function formatKindLabel(kind: ScoreDefinitionKind): string {
    if (kind === 'categorical') {
        return 'Categorical'
    }
    if (kind === 'numeric') {
        return 'Numeric'
    }
    return 'Boolean'
}

export function getModalTitle(mode: ScoreDefinitionModalMode): string {
    return mode === 'create'
        ? 'New scorer'
        : mode === 'duplicate'
          ? 'Duplicate scorer'
          : mode === 'metadata'
            ? 'Edit scorer metadata'
            : 'Edit scorer config'
}

function suggestKey(value: string): string {
    return value
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, '_')
        .replace(/^_+|_+$/g, '')
}

export function getCurrentProjectId(): string {
    return String(ApiConfig.getCurrentTeamId())
}

export function getApiErrorDetail(error: unknown): string | undefined {
    if (error !== null && typeof error === 'object') {
        if ('detail' in error && typeof error.detail === 'string') {
            return error.detail
        }

        if ('data' in error && error.data && typeof error.data === 'object') {
            for (const value of Object.values(error.data as Record<string, unknown>)) {
                if (Array.isArray(value) && typeof value[0] === 'string') {
                    return value[0]
                }
                if (typeof value === 'string') {
                    return value
                }
            }
        }
    }

    return undefined
}

export function parseOptionalNumber(value: string): number | null {
    if (!value.trim()) {
        return null
    }

    const parsedValue = Number(value)
    return Number.isFinite(parsedValue) ? parsedValue : NaN
}

export function parseOptionalInteger(value: string): number | null {
    if (!value.trim()) {
        return null
    }

    const parsedValue = Number(value)
    return Number.isInteger(parsedValue) ? parsedValue : NaN
}

export function getNumericInputValue(value: string): number | undefined {
    const parsedValue = parseOptionalNumber(value)
    return parsedValue === null || Number.isNaN(parsedValue) ? undefined : parsedValue
}

export function getIntegerInputValue(value: string): number | undefined {
    const parsedValue = parseOptionalInteger(value)
    return parsedValue === null || Number.isNaN(parsedValue) ? undefined : parsedValue
}

export function formatNumericInputValue(value: number | undefined): string {
    return typeof value === 'number' && Number.isFinite(value) ? String(value) : ''
}

export function createDraft(
    mode: ScoreDefinitionModalMode,
    scoreDefinition?: ScoreDefinition | null
): ScoreDefinitionDraft {
    const baseDefinition = scoreDefinition || null
    const kind = baseDefinition?.kind || 'categorical'
    const categoricalConfig: CategoricalScoreDefinitionConfig = baseDefinition
        ? getCategoricalConfig(baseDefinition.config)
        : { options: [], selection_mode: 'single' }
    const numericConfig = baseDefinition ? getNumericConfig(baseDefinition.config) : {}
    const booleanConfig = baseDefinition ? getBooleanConfig(baseDefinition.config) : {}

    const defaultOptions =
        categoricalConfig.options.length > 0
            ? categoricalConfig.options.map((option) => ({ ...option }))
            : [
                  { key: 'good', label: 'Good' },
                  { key: 'bad', label: 'Bad' },
              ]

    const duplicatedName = baseDefinition ? `${baseDefinition.name} copy` : ''

    return {
        name: mode === 'duplicate' ? duplicatedName : baseDefinition?.name || '',
        description: baseDefinition?.description || '',
        kind,
        options: defaultOptions,
        selectionMode: categoricalConfig.selection_mode || 'single',
        categoricalMinSelections:
            categoricalConfig.min_selections === undefined || categoricalConfig.min_selections === null
                ? ''
                : String(categoricalConfig.min_selections),
        categoricalMaxSelections:
            categoricalConfig.max_selections === undefined || categoricalConfig.max_selections === null
                ? ''
                : String(categoricalConfig.max_selections),
        numericMin: numericConfig.min === undefined || numericConfig.min === null ? '' : String(numericConfig.min),
        numericMax: numericConfig.max === undefined || numericConfig.max === null ? '' : String(numericConfig.max),
        numericStep: numericConfig.step === undefined || numericConfig.step === null ? '' : String(numericConfig.step),
        trueLabel: booleanConfig.true_label || DEFAULT_BOOLEAN_TRUE_LABEL,
        falseLabel: booleanConfig.false_label || DEFAULT_BOOLEAN_FALSE_LABEL,
    }
}

export function buildConfigFromDraft(draft: ScoreDefinitionDraft): ScoreDefinitionConfig {
    if (draft.kind === 'categorical') {
        const categoricalConfig: CategoricalScoreDefinitionConfig = {
            options: draft.options.map((option) => ({
                key: option.key.trim() || suggestKey(option.label),
                label: option.label.trim(),
            })),
        }

        if (draft.selectionMode === 'multiple') {
            categoricalConfig.selection_mode = 'multiple'

            const minimum = parseOptionalInteger(draft.categoricalMinSelections)
            const maximum = parseOptionalInteger(draft.categoricalMaxSelections)

            if (minimum !== null) {
                categoricalConfig.min_selections = minimum
            }

            if (maximum !== null) {
                categoricalConfig.max_selections = maximum
            }
        }

        return categoricalConfig
    }

    if (draft.kind === 'numeric') {
        const numericConfig: NumericScoreDefinitionConfig = {}
        const minimum = parseOptionalNumber(draft.numericMin)
        const maximum = parseOptionalNumber(draft.numericMax)
        const step = parseOptionalNumber(draft.numericStep)

        if (minimum !== null) {
            numericConfig.min = minimum
        }
        if (maximum !== null) {
            numericConfig.max = maximum
        }
        if (step !== null) {
            numericConfig.step = step
        }

        return numericConfig
    }

    const booleanConfig: BooleanScoreDefinitionConfig = {}
    if (draft.trueLabel.trim()) {
        booleanConfig.true_label = draft.trueLabel.trim()
    }
    if (draft.falseLabel.trim()) {
        booleanConfig.false_label = draft.falseLabel.trim()
    }
    return booleanConfig
}

export function validateDraft(mode: ScoreDefinitionModalMode, draft: ScoreDefinitionDraft): string | undefined {
    if (mode !== 'config' && !draft.name.trim()) {
        return 'Name is required.'
    }

    if (draft.kind === 'categorical') {
        if (draft.options.length === 0) {
            return 'Add at least one categorical option.'
        }

        const optionLabels = new Set<string>()
        const optionKeys = new Set<string>()
        for (const option of draft.options) {
            const normalizedLabel = option.label.trim()
            if (!normalizedLabel) {
                return 'Each categorical option needs a label.'
            }
            const normalizedLabelKey = normalizedLabel.toLowerCase()
            if (optionLabels.has(normalizedLabelKey)) {
                return 'Categorical option labels must be unique.'
            }
            optionLabels.add(normalizedLabelKey)

            const normalizedKey = option.key.trim() || suggestKey(normalizedLabel)
            if (!normalizedKey) {
                return 'Categorical option labels must include letters or numbers.'
            }
            if (optionKeys.has(normalizedKey)) {
                return 'Some option labels are too similar and would generate duplicate IDs. Please use more distinct labels.'
            }
            optionKeys.add(normalizedKey)
        }

        if (draft.selectionMode === 'multiple') {
            const selectionValues = [draft.categoricalMinSelections, draft.categoricalMaxSelections]
            if (selectionValues.some((value) => value.trim() && Number.isNaN(parseOptionalInteger(value)))) {
                return 'Selection bounds must be whole numbers.'
            }

            const minimum = parseOptionalInteger(draft.categoricalMinSelections)
            const maximum = parseOptionalInteger(draft.categoricalMaxSelections)

            if (minimum !== null && minimum > draft.options.length) {
                return 'Minimum selections cannot exceed the number of options.'
            }

            if (maximum !== null && maximum > draft.options.length) {
                return 'Maximum selections cannot exceed the number of options.'
            }

            if (minimum !== null && maximum !== null && minimum > maximum) {
                return 'Maximum selections must be greater than or equal to minimum selections.'
            }
        }
    }

    if (draft.kind === 'numeric') {
        const numericValues = [draft.numericMin, draft.numericMax, draft.numericStep]
        if (numericValues.some((value) => value.trim() && Number.isNaN(parseOptionalNumber(value)))) {
            return 'Numeric bounds must be valid numbers.'
        }

        const minimum = parseOptionalNumber(draft.numericMin)
        const maximum = parseOptionalNumber(draft.numericMax)
        if (minimum !== null && maximum !== null && minimum > maximum) {
            return 'Numeric max must be greater than or equal to min.'
        }
    }

    return undefined
}
