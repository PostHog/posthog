import { ExperimentMetric, NewExperimentQueryResponse } from '~/queries/schema/schema-general'

import { VariantTag } from '../ExperimentView/VariantTag'
import {
    ExperimentVariantResult,
    formatChanceToWinForGoal,
    getChanceToWin,
    isBayesianResult,
} from '../MetricsView/shared/utils'

type NotebookWinningVariantSummaryProps = {
    result: NewExperimentQueryResponse
    metric: ExperimentMetric
}

function getWinningVariant(
    result: NewExperimentQueryResponse,
    goal: 'increase' | 'decrease' | undefined
): { variantKey: string; chanceToWin: number } | null {
    if (!result.variant_results?.length) {
        return null
    }

    const winner = result.variant_results
        .filter(isBayesianResult)
        .map((variant) => ({
            variant,
            chanceToWin: getChanceToWin(variant, goal) ?? -1,
        }))
        .reduce<{ variant: ExperimentVariantResult; chanceToWin: number } | null>(
            (best, current) => (current.chanceToWin > (best?.chanceToWin ?? -1) ? current : best),
            null
        )

    if (!winner || winner.chanceToWin <= 0) {
        return null
    }

    return {
        variantKey: winner.variant.key,
        chanceToWin: winner.chanceToWin,
    }
}

export function NotebookWinningVariantSummary({ result, metric }: NotebookWinningVariantSummaryProps): JSX.Element {
    const goal = 'goal' in metric ? metric.goal : undefined
    const winning = getWinningVariant(result, goal)

    if (!winning) {
        return <div className="text-sm text-muted">Collecting data...</div>
    }

    const formattedChance = formatChanceToWinForGoal(
        result.variant_results.find((v) => v.key === winning.variantKey) as ExperimentVariantResult,
        goal
    )

    return (
        <div className="text-sm flex items-center gap-1 flex-wrap">
            <VariantTag variantKey={winning.variantKey} />
            <span>is winning with</span>
            <span className="font-semibold">{formattedChance}</span>
            <span>probability</span>
        </div>
    )
}
