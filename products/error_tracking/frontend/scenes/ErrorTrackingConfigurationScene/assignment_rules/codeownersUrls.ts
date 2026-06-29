import { AnyPropertyFilter } from '~/types'

import { matchingExceptionsUrl, matchingIssuesUrl } from '../rules/ruleMatchUrls'
import { buildOwnerFilters } from './codeownersImport'

export function exceptionsUrl(patterns: string[], dateRange: string): string {
    const filters = buildOwnerFilters(patterns)
    return matchingExceptionsUrl(filters.values as AnyPropertyFilter[], dateRange)
}

export function issuesUrl(patterns: string[], dateRange: string): string {
    const filters = buildOwnerFilters(patterns)
    return matchingIssuesUrl(filters.values as AnyPropertyFilter[], filters.type, dateRange)
}
