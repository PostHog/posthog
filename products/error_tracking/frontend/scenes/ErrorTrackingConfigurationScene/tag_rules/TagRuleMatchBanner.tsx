import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Link } from '@posthog/lemon-ui'

import { UniversalFiltersGroup } from '~/types'

import { firstExceptionsOfNewIssuesUrl } from './tagRuleMatch'
import { tagRuleModalLogic } from './tagRuleModalLogic'

const NEXT_DATE_RANGE: Record<string, string> = { '-7d': '-30d', '-30d': '-90d' }

function daysLabel(dateRange: string): string {
    return `${Number(dateRange.slice(1, -1))} days`
}

export function TagRuleMatchBanner(): JSX.Element | null {
    const { rule, matchResult, matchResultLoading, dateRange } = useValues(tagRuleModalLogic)
    const { increaseDateRange } = useActions(tagRuleModalLogic)

    if (matchResult === null || matchResultLoading) {
        return null
    }

    const nextRange = NEXT_DATE_RANGE[dateRange]
    if (matchResult.issueCount === 0) {
        return (
            <LemonBanner type="error">
                <div className="flex items-center justify-between gap-2">
                    <span>{`No new issue in the last ${daysLabel(dateRange)} started with a matching exception`}</span>
                    {nextRange && (
                        <LemonButton type="secondary" size="xsmall" onClick={increaseDateRange}>
                            {`Try last ${daysLabel(nextRange)}`}
                        </LemonButton>
                    )}
                </div>
            </LemonBanner>
        )
    }

    const url = firstExceptionsOfNewIssuesUrl(rule.filters as UniversalFiltersGroup, dateRange)
    return (
        <LemonBanner type="success">
            <Link to={`${window.location.origin}${url}`} target="_blank" targetBlankIcon={false}>
                {`${matchResult.issueCount.toLocaleString()} new ${matchResult.issueCount === 1 ? 'issue' : 'issues'}`}
            </Link>
            <span>{` in the last ${daysLabel(dateRange)} started with a matching exception and would have got this tag`}</span>
        </LemonBanner>
    )
}
