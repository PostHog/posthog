import type {
    GoalScoutDetailApi,
    GoalScoutDirectionEnumApi,
    GoalScoutGuardrailApi,
    GoalScoutWriteApi,
} from 'products/signals/frontend/generated/api.schemas'

export interface GoalFormValues {
    statement: string
    title: string
    area: string
    repositories: string[]
    goal_insight: string
    goal_description: string
    goal_metric: string
    target: string
    direction: GoalScoutDirectionEnumApi
    unit: string
    budget: string
    secondary_metrics: GoalScoutGuardrailApi[]
    ideas: string[]
}

export type GoalFormField = 'statement' | 'title' | 'goal_insight' | 'target' | 'guardrails' | 'budget' | 'repository'

export interface GoalInsightOption {
    value: string
    label: string
    disabledReason: string | null
}

export interface GoalMissingPart {
    field: GoalFormField
    label: string
}

export type GoalFormProblems = Partial<Record<GoalFormField, string>>

export const MAX_OWNER_IDEAS = 5
export const MAX_GUARDRAILS = 5
export const MIN_BELIEF_FOR_MEASURES = 20
export const TARGET_PATTERN = /^-?\d{0,16}(?:\.\d{0,4})?$/
const REPOSITORY_PATTERN = /^[\w.-]+\/[\w.-]+$/
const DEFAULT_BUDGET = '20'

export const LOCKED_REASON = 'This is locked once the goal runs. Close the goal and create a new one to change it.'

export const FIELD_LABELS: Record<GoalFormField, string> = {
    statement: 'belief',
    title: 'name',
    goal_insight: 'measure',
    target: 'target',
    guardrails: 'guardrail direction',
    budget: 'budget',
    repository: 'repository',
}

export const SERVER_FIELDS: Record<string, GoalFormField> = {
    statement: 'statement',
    title: 'title',
    goal_insight: 'goal_insight',
    goal_description: 'goal_insight',
    target: 'target',
    secondary_metrics: 'guardrails',
    budget_cents: 'budget',
    repositories: 'repository',
}

export const EMPTY_GOAL_FORM: GoalFormValues = {
    statement: '',
    title: '',
    area: '',
    repositories: [],
    goal_insight: '',
    goal_description: '',
    goal_metric: '',
    target: '',
    direction: 'increase',
    unit: '',
    budget: DEFAULT_BUDGET,
    secondary_metrics: [],
    ideas: [],
}

export function formFromGoal(goal: GoalScoutDetailApi): GoalFormValues {
    return {
        statement: goal.statement,
        title: goal.title,
        area: goal.area,
        repositories: goal.repositories,
        goal_insight: goal.goal_insight,
        goal_description: goal.goal_description,
        goal_metric: goal.goal_metric,
        secondary_metrics: goal.secondary_metrics,
        target: goal.target === null ? '' : String(Number(goal.target)),
        direction: goal.direction,
        unit: goal.unit,
        budget: String(goal.money.allocated_cents / 100),
        ideas: [],
    }
}

export function writeFromGoal(goal: GoalScoutDetailApi): GoalScoutWriteApi {
    return {
        title: goal.title,
        statement: goal.statement,
        area: goal.area,
        repositories: goal.repositories,
        goal_insight: goal.goal_insight,
        goal_description: goal.goal_description,
        goal_metric: goal.goal_metric,
        secondary_metrics: goal.secondary_metrics,
        target: goal.target === null ? null : String(Number(goal.target)),
        direction: goal.direction,
        unit: goal.unit,
        budget_cents: goal.money.allocated_cents,
    }
}

export function budgetCents(budget: string): number | null {
    const value = Number(budget)
    return budget.trim() && Number.isFinite(value) && value >= 0 ? Math.round(value * 100) : null
}

export function targetNumber(target: string): number | null {
    const value = target.trim()
    return value && value !== '-' && TARGET_PATTERN.test(value) ? Number(value) : null
}

export const LOCKED_FIELDS: (keyof GoalScoutWriteApi)[] = [
    'goal_insight',
    'goal_description',
    'goal_metric',
    'unit',
    'direction',
    'secondary_metrics',
    'repositories',
]

export function changedFields(
    next: GoalScoutWriteApi,
    initial: GoalScoutWriteApi,
    skip: (keyof GoalScoutWriteApi)[]
): Partial<GoalScoutWriteApi> {
    return Object.fromEntries(
        Object.entries(next).filter(
            ([field, value]) =>
                !skip.includes(field as keyof GoalScoutWriteApi) &&
                JSON.stringify(value) !== JSON.stringify(initial[field as keyof GoalScoutWriteApi])
        )
    )
}

interface GoalFormProblemsInput {
    form: GoalFormValues
    title: string
    ineligibleReason: string | null
    target: number | null
    current: number | null
    budgetRequired: boolean
    repositories: string[]
    describing: boolean
    insightNames: Record<string, string>
}

export function goalFormProblems(input: GoalFormProblemsInput): GoalFormProblems {
    const { form, title, ineligibleReason, target, current, repositories, describing } = input
    const problems: GoalFormProblems = {}
    if (!form.statement.trim()) {
        problems.statement = 'Say what you believe will improve.'
    }
    if (!title.trim()) {
        problems.title = 'Give the goal scout a short name.'
    }
    if (describing) {
        if (!form.goal_description.trim()) {
            problems.goal_insight = 'Describe how the scout should measure this goal.'
        }
    } else if (!form.goal_insight) {
        problems.goal_insight = 'Choose the insight that measures this goal.'
    } else if (ineligibleReason) {
        problems.goal_insight = ineligibleReason
    }
    const targetProblem = !form.target.trim()
        ? 'Enter the value you want to reach.'
        : target === null
          ? 'Enter a number with up to 4 decimals.'
          : current !== null && target === current
            ? 'Pick a target that is different from the current value.'
            : null
    if (targetProblem && !describing && form.goal_insight) {
        problems.target = targetProblem
    }
    const undecided = form.secondary_metrics.find((metric) => !metric.direction)
    if (undecided) {
        problems.guardrails = `Choose which way is better for ${
            input.insightNames[undecided.insight] || undecided.name || 'each guardrail'
        }.`
    }
    const cents = budgetCents(form.budget)
    if (cents === null || (input.budgetRequired && cents === 0)) {
        problems.budget = 'Enter a budget above $0.'
    }
    if (!repositories.length) {
        problems.repository = 'Choose the repository where the scout opens pull requests.'
    } else if (repositories.some((repository) => !REPOSITORY_PATTERN.test(repository.trim()))) {
        problems.repository = 'Use the owner/repository form.'
    }
    return problems
}

export function missingSummary(missing: GoalMissingPart[], problems: GoalFormProblems): string | null {
    if (missing.length === 1) {
        return problems[missing[0].field] ?? null
    }
    if (!missing.length) {
        return null
    }
    const labels = missing
        .map((part) => part.label)
        .join(', ')
        .replace(/, ([^,]*)$/, ' and $1')
    return `Fill in the ${labels} first.`
}

const BELIEF_LIMIT = 180

function beliefClause(belief: string): string {
    const plain = belief
        .replace(/\s+/g, ' ')
        .trim()
        .replace(/^(we|i) (believe|think|bet)( that)?\s+/i, '')
        .replace(/^if\s+/i, '')
        .replace(/([.!?])\s+[A-Z].*$/, '$1')
        .replace(/,?\s+because\b.*$/i, '')
        .replace(/[.!?;:,\s]+$/, '')
    if (!plain) {
        return ''
    }
    const first = plain.split(' ')[0]
    const keepCase = first.length > 1 && /[A-Z]/.test(first.slice(1))
    const cased = keepCase ? plain : plain[0].toLowerCase() + plain.slice(1)
    if (cased.length <= BELIEF_LIMIT) {
        return cased
    }
    const cut = cased.slice(0, BELIEF_LIMIT)
    return `${cut.slice(0, cut.lastIndexOf(' ') > 0 ? cut.lastIndexOf(' ') : BELIEF_LIMIT)}…`
}

const SUBJECT_END =
    /^(will|would|can|could|should|may|might|is|are|was|were|makes?|helps?|keeps?|gets?|leads?|increases?|reduces?|improves?|drives?|lets?|means?|raises?|lowers?|cuts?|brings?|turns?)$/i
const NAME_LIMIT = 60
const TRAILING_WORDS = /^(of|the|a|an|to|for|and|or|in|on|with|who|that|which|at|by|from)$/i

export function nameFromBelief(belief: string): string {
    const clause = beliefClause(belief).replace(/…$/, '').split(/[,;:]/)[0]
    const words = clause.split(' ').filter(Boolean)
    const end = words.findIndex((word, index) => index > 0 && SUBJECT_END.test(word))
    const fitting = words.filter((_, index) => words.slice(0, index + 1).join(' ').length <= NAME_LIMIT)
    const subject = (end > 1 && end <= 8 ? words.slice(0, end) : fitting).filter(
        (word, index) => index > 0 || !/^(a|an|the)$/i.test(word)
    )
    while (subject.length > 1 && TRAILING_WORDS.test(subject[subject.length - 1])) {
        subject.pop()
    }
    const name = subject.join(' ')
    return name ? name[0].toUpperCase() + name.slice(1) : ''
}
