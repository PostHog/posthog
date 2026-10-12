export type AiLab = 'Anthropic' | 'OpenAI' | 'Google' | 'xAI' | 'Cursor' | 'Open weights'
export type ModelLab = AiLab | 'Other'

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
