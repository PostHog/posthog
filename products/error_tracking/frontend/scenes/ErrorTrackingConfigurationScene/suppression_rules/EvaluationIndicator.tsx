import { IconLaptop, IconServer } from '@posthog/icons'
import { Tooltip } from '@posthog/lemon-ui'

import { FilterLogicalOperator, UniversalFiltersGroup, UniversalFiltersGroupValue } from '~/types'

// Kept in sync with SERVER_ONLY_PROPERTIES and CLIENT_EVALUABLE_OPERATORS in
// products/error_tracking/backend/logic/__init__.py, which decides what actually reaches the SDK.
// Showing a rule as client-evaluated when the backend withholds it tells the user the wrong thing
// about where their rule runs.
const SERVER_ONLY_PROPERTIES = new Set(['$exception_sources', '$exception_functions'])
const CLIENT_EVALUABLE_OPERATORS = new Set([
    'exact',
    'is_not',
    'regex',
    'not_regex',
    'icontains',
    'not_icontains',
    'gt',
    'lt',
])

function isFilterClientSafe(f: UniversalFiltersGroupValue): boolean {
    // A rule can nest groups, and the backend recurses into them, so a group is safe when its
    // leaves are. Treating one as a leaf here reads its missing operator as unevaluable.
    if ('values' in f) {
        return (f.values ?? []).every(isFilterClientSafe)
    }
    if ('key' in f && f.key && SERVER_ONLY_PROPERTIES.has(f.key)) {
        return false
    }
    const operator = 'operator' in f ? f.operator : undefined
    return !!operator && CLIENT_EVALUABLE_OPERATORS.has(operator)
}

export type EvalMode = 'client' | 'partial' | 'server'

export function getEvalMode(filters: UniversalFiltersGroup): EvalMode {
    const values = filters.values ?? []
    if (values.length === 0) {
        return 'client'
    }

    const safeCount = values.filter(isFilterClientSafe).length

    if (safeCount === values.length) {
        return 'client'
    }
    if (safeCount > 0 && filters.type === FilterLogicalOperator.Or) {
        return 'partial'
    }
    return 'server'
}

function Pill({
    activeClasses,
    icon: Icon,
    label,
    tooltip,
}: {
    activeClasses: string
    icon: typeof IconLaptop
    label: string
    tooltip: string
}): JSX.Element {
    return (
        <Tooltip title={tooltip}>
            <div className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium ${activeClasses}`}>
                <Icon className="text-base" />
                {label}
            </div>
        </Tooltip>
    )
}

const CLIENT_TOOLTIPS: Record<EvalMode, string> = {
    client: 'Exceptions are dropped by the SDK before being sent to PostHog',
    partial: 'Some filters can be evaluated client-side. If any match, the SDK drops the exception without sending it.',
    server: 'This rule cannot be evaluated client-side',
}

const SERVER_TOOLTIPS: Record<EvalMode, string> = {
    client: 'Also evaluated server-side during ingestion as a fallback',
    partial: 'Evaluated server-side during ingestion for filters that cannot run client-side',
    server: 'Exceptions are sent to PostHog and evaluated during ingestion',
}

function DonutChart({
    percentage,
    size = 16,
    className,
}: {
    percentage: number
    size?: number
    className?: string
}): JSX.Element {
    const strokeWidth = 3
    const radius = (size - strokeWidth) / 2
    const circumference = 2 * Math.PI * radius
    const filled = (percentage / 100) * circumference
    const center = size / 2

    return (
        <svg
            width={size}
            height={size}
            viewBox={`0 0 ${size} ${size}`}
            className={`shrink-0 -rotate-90 ${className ?? ''}`}
        >
            <circle
                cx={center}
                cy={center}
                r={radius}
                fill="none"
                stroke="currentColor"
                strokeWidth={strokeWidth}
                opacity={0.2}
            />
            <circle
                cx={center}
                cy={center}
                r={radius}
                fill="none"
                stroke="currentColor"
                strokeWidth={strokeWidth}
                strokeDasharray={`${filled} ${circumference - filled}`}
                strokeLinecap="round"
            />
        </svg>
    )
}

export function SamplingRateIndicator({ samplingRate }: { samplingRate: number }): JSX.Element {
    const percentage = Math.round(samplingRate * 100)
    return (
        <Tooltip
            title={`${percentage}% of matching exceptions will be suppressed. The remaining ${100 - percentage}% will be captured normally.`}
        >
            <div className="inline-flex items-center gap-1.5 text-xs text-secondary">
                <DonutChart percentage={percentage} className="text-danger" />
                {percentage}% suppressed
            </div>
        </Tooltip>
    )
}

export function EvaluationIndicator({ mode }: { mode: EvalMode }): JSX.Element {
    const clientActive = mode === 'client' || mode === 'partial'
    return (
        <div className="inline-flex items-center gap-1">
            {clientActive && (
                <Pill
                    activeClasses="bg-success-highlight text-success"
                    icon={IconLaptop}
                    label="Client"
                    tooltip={CLIENT_TOOLTIPS[mode]}
                />
            )}
            {mode !== 'client' && (
                <Pill
                    activeClasses="bg-warning-highlight text-warning"
                    icon={IconServer}
                    label="Server"
                    tooltip={SERVER_TOOLTIPS[mode]}
                />
            )}
        </div>
    )
}
