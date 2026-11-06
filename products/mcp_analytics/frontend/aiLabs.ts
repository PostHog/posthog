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
    ['OpenAI', /gpt|(?:^|[^a-z0-9_])o[1-9]|codex|openai|chatgpt/],
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

// Matches the posthog.com MCP leaderboard, which names the same number of models on its model chart.
export const TOP_MODEL_COUNT = 10

export function topModels(totals: Iterable<[model: string, calls: number]>): Set<string> {
    return new Set(
        [...totals]
            .filter(([model]) => model !== 'Other' && model !== UNKNOWN)
            .sort(([modelA, callsA], [modelB, callsB]) => callsB - callsA || modelA.localeCompare(modelB))
            .slice(0, TOP_MODEL_COUNT)
            .map(([model]) => model)
    )
}

// The row each model shows in on the model charts. A lab with a single model outside the top keeps that
// model's name, because a one-model "Other <lab> models" row only hides it.
export function modelRowLabels(models: string[], top: ReadonlySet<string>): Map<string, string> {
    const leftovers = new Map<string, number>()
    for (const model of models) {
        if (!top.has(model)) {
            const label = foldedModelLabel(model)
            leftovers.set(label, (leftovers.get(label) ?? 0) + 1)
        }
    }
    return new Map(
        models.map((model) => {
            const label = foldedModelLabel(model)
            const keepsName = top.has(model) || (model !== 'Other' && leftovers.get(label) === 1)
            return [model, keepsName ? model : label]
        })
    )
}

// The row of every model, from the calls each model has. Build it once per page from the fullest model
// list, so every chart on the page puts a model in the same row.
export function modelRowLabelsByCalls(totals: Iterable<[model: string, calls: number]>): Map<string, string> {
    const named = [...totals].filter(([model]) => model !== UNKNOWN)
    return modelRowLabels(
        named.map(([model]) => model),
        topModels(named)
    )
}

export function isFoldedModelsLabel(label: string): boolean {
    return LAB_ORDER.some((lab) => otherModelsLabel(lab) === label)
}

export function seriesLab(label: string): ModelLab {
    return LAB_ORDER.find((lab) => otherModelsLabel(lab) === label) ?? modelLab(label)
}
