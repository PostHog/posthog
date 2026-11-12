import type { ReportSpendApi } from 'products/signals/frontend/generated/api.schemas'

import { formatCredits } from '../../utils/credits'

/** What the closed Spend line says: the usage of the report itself, without the shared scout runs. */
export function reportSpendLine(spend: ReportSpendApi): string {
    const amounts = [spend.generation.total_spend, spend.implementation.total_spend].filter(
        (amount): amount is number => amount !== null
    )
    if (amounts.length === 0) {
        return 'Not tracked'
    }
    const total = formatCredits(amounts.reduce((sum, amount) => sum + amount, 0))
    return spend.generation.incomplete || spend.implementation.incomplete ? `${total} so far` : total
}
