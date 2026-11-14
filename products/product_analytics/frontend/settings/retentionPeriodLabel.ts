import { pluralize } from 'lib/utils/strings'

export function retentionPeriodLabel(months: number): string {
    return months % 12 === 0 ? pluralize(months / 12, 'year') : pluralize(months, 'month')
}
