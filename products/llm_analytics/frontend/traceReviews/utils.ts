import type {
    BooleanScoreDefinitionConfigApi as BooleanScoreDefinitionConfig,
    CategoricalScoreDefinitionConfigApi as CategoricalScoreDefinitionConfig,
    NumericScoreDefinitionConfigApi as NumericScoreDefinitionConfig,
    ScoreDefinitionConfigApi as ScoreDefinitionConfig,
} from '../generated/api.schemas'
import type { TraceReview, TraceReviewScore } from './types'

const DEFAULT_BOOLEAN_TRUE_LABEL = 'Yes'
const DEFAULT_BOOLEAN_FALSE_LABEL = 'No'

export function formatNumericTraceReviewScore(value: string | number | null | undefined): string {
    if (value === null || value === undefined || value === '') {
        return ''
    }

    return String(value)
        .replace(/(\.\d*?)0+$/, '$1')
        .replace(/\.$/, '')
}

export function getCategoricalConfig(config: ScoreDefinitionConfig): CategoricalScoreDefinitionConfig {
    return 'options' in config ? config : { options: [] }
}

export function getNumericConfig(config: ScoreDefinitionConfig): NumericScoreDefinitionConfig {
    return 'min' in config || 'max' in config || 'step' in config ? config : {}
}

export function getBooleanConfig(config: ScoreDefinitionConfig): BooleanScoreDefinitionConfig {
    return 'true_label' in config || 'false_label' in config ? config : {}
}

export function getTraceReviewScoreDisplayValue(score: TraceReviewScore): string {
    if (score.definition_kind === 'categorical') {
        const config = getCategoricalConfig(score.definition_config)
        const matchingOption = config.options.find((option) => option.key === score.categorical_value)
        return matchingOption?.label || score.categorical_value || 'Reviewed'
    }

    if (score.definition_kind === 'numeric') {
        return formatNumericTraceReviewScore(score.numeric_value)
    }

    const config = getBooleanConfig(score.definition_config)
    if (score.boolean_value === true) {
        return config.true_label || DEFAULT_BOOLEAN_TRUE_LABEL
    }

    return config.false_label || DEFAULT_BOOLEAN_FALSE_LABEL
}

export function getTraceReviewDisplayValue(review: TraceReview): string {
    if (review.scores.length === 0) {
        return 'Reviewed'
    }

    if (review.scores.length === 1) {
        const score = review.scores[0]
        const summary = `${score.definition_name}: ${getTraceReviewScoreDisplayValue(score)}`
        return summary.length <= 24 ? summary : '1 score'
    }

    return `${review.scores.length} scores`
}

export function getTraceReviewStatusDisplayValue(review: TraceReview | null): string {
    if (!review) {
        return 'Not reviewed'
    }

    if (review.scores.length === 0) {
        return 'Reviewed'
    }

    return review.scores.length === 1
        ? `Reviewed: ${getTraceReviewDisplayValue(review)}`
        : `Reviewed: ${review.scores.length} scores`
}

export function getTraceReviewTagType(review: TraceReview): 'success' | 'completion' {
    return review.scores.length === 0 ? 'success' : 'completion'
}

export function getTraceReviewStatusTagType(review: TraceReview | null): 'success' | 'completion' | 'muted' {
    if (!review) {
        return 'muted'
    }

    return getTraceReviewTagType(review)
}

export function getTraceReviewerName(review: TraceReview): string | null {
    const reviewer = review.reviewed_by

    if (!reviewer) {
        return null
    }

    if (reviewer.first_name) {
        return reviewer.first_name
    }

    if (reviewer.email) {
        return reviewer.email
    }

    if (reviewer.distinct_id) {
        return reviewer.distinct_id
    }

    return null
}
