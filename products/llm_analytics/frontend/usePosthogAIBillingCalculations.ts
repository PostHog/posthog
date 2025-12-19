import { useValues } from 'kea'
import { useMemo } from 'react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { EnrichedTraceTreeNode } from './llmAnalyticsTraceDataLogic'
import { isLLMEvent } from './utils'

// AI billing markup: 20% markup on top of cost
const AI_COST_MARKUP_PERCENT = 0.2

// Banker's rounding
function roundBankers(value: number): number {
    const rounded = Math.round(value)
    const diff = Math.abs(value - rounded + 0.5)

    // If not exactly X.5 (accounting for floating-point precision), use standard rounding
    if (diff > Number.EPSILON) {
        return Math.round(value)
    }

    // For X.5, round to nearest even
    const lower = Math.floor(value)
    return lower % 2 === 0 ? lower : lower + 1
}

interface BillingCalculations {
    showBillingInfo: boolean
    totalCostUsd: number
    markupUsd: number
    billedTotalUsd: number
    billedCredits: number
}

export function usePosthogAIBillingCalculations(enrichedTree: EnrichedTraceTreeNode[] | null): BillingCalculations {
    const { featureFlags } = useValues(featureFlagLogic)

    const showBillingInfo = !!featureFlags[FEATURE_FLAGS.POSTHOG_AI_BILLING_DISPLAY]

    // Compute total billed USD across billed generations in the tree
    const totalCostUsd = useMemo(() => {
        if (!showBillingInfo || !enrichedTree) {
            return 0
        }

        const sumBilled = (node: EnrichedTraceTreeNode): number => {
            const ev = node.event
            let total = 0
            if (isLLMEvent(ev) && ev.event === '$ai_generation' && !!ev.properties?.$ai_billable) {
                const cost = Number(ev.properties.$ai_total_cost_usd ?? 0)
                total += isNaN(cost) ? 0 : cost
            }
            if (node.children) {
                for (const child of node.children) {
                    total += sumBilled(child)
                }
            }
            return total
        }

        return enrichedTree.reduce((acc, n) => acc + sumBilled(n), 0)
    }, [enrichedTree, showBillingInfo])

    const markupUsd = showBillingInfo ? totalCostUsd * AI_COST_MARKUP_PERCENT : 0
    const billedTotalUsd = showBillingInfo ? totalCostUsd + markupUsd : 0 // Total cost + markup
    const billedCredits = showBillingInfo ? roundBankers(billedTotalUsd * 100) : 0

    return {
        showBillingInfo,
        totalCostUsd,
        markupUsd,
        billedTotalUsd,
        billedCredits,
    }
}
