import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { BuiltInFilterRow } from './BuiltInFilterRow'
import { builtInFiltersLogic } from './builtInFiltersLogic'

export function BuiltInFilters(): JSX.Element {
    const { builtInFilters, builtInFiltersLoadFailed, pendingKeys } = useValues(builtInFiltersLogic)
    const { loadBuiltInFilters, setFilterEnabled } = useActions(builtInFiltersLogic)
    const editDisabledReason = errorTrackingEditAccessDisabledReason()

    if (builtInFiltersLoadFailed) {
        return (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadBuiltInFilters() }}>
                Couldn't load the automatic suppression rules.
            </LemonBanner>
        )
    }

    if (builtInFilters === null) {
        return <LemonSkeleton className="h-14" repeat={3} />
    }

    return (
        <div className="rounded border bg-surface-primary divide-y">
            {builtInFilters.map((filter) => (
                <BuiltInFilterRow
                    key={filter.key}
                    filter={filter}
                    saving={pendingKeys.includes(filter.key)}
                    editDisabledReason={editDisabledReason}
                    onSetEnabled={(enabled) => setFilterEnabled(filter.key, enabled)}
                />
            ))}
        </div>
    )
}
