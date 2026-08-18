import { useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { issueFiltersLogic } from './issueFiltersLogic'

// Warns when a filter excludes a value on a property that some events never set.
// The engine reads a missing property as empty, so the filter keeps those events and
// the issue list does not shrink as the user expects.
export function NegatedFilterWarning(): JSX.Element | null {
    const { negatedUnsetPropertyKeys } = useValues(issueFiltersLogic)

    if (negatedUnsetPropertyKeys.length === 0) {
        return null
    }

    return (
        <LemonBanner type="warning" className="w-full text-xs">
            <span>
                A filter that excludes a value on{' '}
                {negatedUnsetPropertyKeys.map((key, index) => (
                    <span key={key}>
                        {index > 0 && ', '}
                        <code>{key}</code>
                    </span>
                ))}{' '}
                also keeps events that never set it, so those issues stay in the list. To exclude them reliably, filter
                on <code>$exception_types</code> or <code>$exception_values</code>, which every exception sets, or use
                the Issue filters.
            </span>
        </LemonBanner>
    )
}
