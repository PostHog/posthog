export type AiLab = 'Anthropic' | 'OpenAI' | 'Google' | 'xAI' | 'Cursor' | 'Open weights'
export type ModelLab = AiLab | 'Other'

export const LAB_ORDER: ModelLab[] = ['Anthropic', 'OpenAI', 'xAI', 'Google', 'Open weights', 'Cursor', 'Other']

const UNKNOWN = 'Unknown'

// The first matching pattern wins. The SQL for the users query is built from the same list, so the
// two cannot disagree on which lab a model belongs to.
const LAB_PATTERNS: [AiLab, RegExp][] = [
    [
        'Open weights',
        /gpt-oss|deepseek|glm|kimi|qwen|llama|mistral|minimax|gemma|nemotron|olmo|devstral|codestral|mimo|^phi/,
    ],
    ['Anthropic', /claude|opus|sonnet|haiku|fable|anthropic/],
    ['OpenAI', /gpt|^o[1-9]|codex|openai|chatgpt/],
    ['Google', /gemini|google/],
    ['xAI', /grok|xai/],
    ['Cursor', /composer/],
]

export function modelLab(model: string): ModelLab {
    const m = model.toLowerCase()
    return LAB_PATTERNS.find(([, pattern]) => pattern.test(m))?.[0] ?? 'Other'
}

export function labSqlExpression(modelSql: string): string {
    const branches = LAB_PATTERNS.map(([lab, pattern]) => `match(lower(${modelSql}), '${pattern.source}'), '${lab}'`)
    return `multiIf(${modelSql} = '${UNKNOWN}', '${UNKNOWN}', ${branches.join(', ')}, 'Other')`
}

export function otherModelsLabel(lab: ModelLab): string {
    return lab === 'Other' ? 'Other models' : `Other ${lab} models`
}

// The series a model outside the top models folds into. The backend's own "Other" row holds the models
// beyond its row limit, from any lab, so it folds into the lab-less series.
export function foldedModelLabel(model: string): string {
    return otherModelsLabel(model === 'Other' ? 'Other' : modelLab(model))
}

export function isFoldedModelsLabel(label: string): boolean {
    return LAB_ORDER.some((lab) => otherModelsLabel(lab) === label)
}

export function seriesLab(label: string): ModelLab {
    return LAB_ORDER.find((lab) => otherModelsLabel(lab) === label) ?? modelLab(label)
}
