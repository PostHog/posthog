import { useActions, useValues } from 'kea'

import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemGroup, Skeleton } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { BuiltInFilterRow } from './BuiltInFilterRow'
import { builtInFiltersLogic } from './builtInFiltersLogic'

export function BuiltInFilters(): JSX.Element {
    const { builtInFilters, builtInFiltersLoadFailed, pendingKeys } = useValues(builtInFiltersLogic)
    const { loadBuiltInFilters, setFilterEnabled } = useActions(builtInFiltersLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const editDisabledReason = errorTrackingEditAccessDisabledReason()

    if (builtInFiltersLoadFailed) {
        return todayRailNav ? (
            <Item tone="destructive" size="sm">
                <ItemContent>
                    <ItemDescription>Couldn't load the automatic suppression rules.</ItemDescription>
                </ItemContent>
                <ItemActions>
                    <Button variant="outline" onClick={() => loadBuiltInFilters()}>
                        Try again
                    </Button>
                </ItemActions>
            </Item>
        ) : (
            <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadBuiltInFilters() }}>
                Couldn't load the automatic suppression rules.
            </LemonBanner>
        )
    }

    if (builtInFilters === null) {
        return todayRailNav ? (
            <div className="flex flex-col gap-2">
                <Skeleton className="h-14" />
                <Skeleton className="h-14" />
                <Skeleton className="h-14" />
            </div>
        ) : (
            <LemonSkeleton className="h-14" repeat={3} />
        )
    }

    const rows = builtInFilters.map((filter) => (
        <BuiltInFilterRow
            key={filter.key}
            filter={filter}
            saving={pendingKeys.includes(filter.key)}
            editDisabledReason={editDisabledReason}
            onSetEnabled={(enabled) => setFilterEnabled(filter.key, enabled)}
        />
    ))

    if (todayRailNav) {
        return <ItemGroup>{rows}</ItemGroup>
    }

    return <div className="rounded border bg-surface-primary divide-y">{rows}</div>
}
