import { pluralize } from 'lib/utils/strings'

/** A retention window as people say it: whole years as years ("3 years"), anything else as months ("18 months"). */
export function retentionPeriodLabel(months: number): string {
    return months % 12 === 0 ? pluralize(months / 12, 'year') : pluralize(months, 'month')
}
