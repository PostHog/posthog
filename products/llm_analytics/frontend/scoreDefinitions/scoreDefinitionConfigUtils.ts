import type {
    BooleanScoreDefinitionConfigApi as BooleanScoreDefinitionConfig,
    CategoricalScoreDefinitionConfigApi as CategoricalScoreDefinitionConfig,
    NumericScoreDefinitionConfigApi as NumericScoreDefinitionConfig,
    ScoreDefinitionConfigApi as ScoreDefinitionConfig,
} from '../generated/api.schemas'

function isRecord(value: unknown): value is Record<string, unknown> {
    return !!value && typeof value === 'object' && !Array.isArray(value)
}

function isCategoricalConfig(config: ScoreDefinitionConfig): config is CategoricalScoreDefinitionConfig {
    return isRecord(config) && Array.isArray(config.options)
}

export function getCategoricalConfig(config: ScoreDefinitionConfig): CategoricalScoreDefinitionConfig {
    if (!isCategoricalConfig(config)) {
        return { options: [], selection_mode: 'single' }
    }

    return {
        ...config,
        selection_mode: config.selection_mode === 'multiple' ? 'multiple' : 'single',
    }
}

export function getNumericConfig(config: ScoreDefinitionConfig): NumericScoreDefinitionConfig {
    return isRecord(config) && ('min' in config || 'max' in config || 'step' in config) ? config : {}
}

export function getBooleanConfig(config: ScoreDefinitionConfig): BooleanScoreDefinitionConfig {
    return isRecord(config) && ('true_label' in config || 'false_label' in config) ? config : {}
}
