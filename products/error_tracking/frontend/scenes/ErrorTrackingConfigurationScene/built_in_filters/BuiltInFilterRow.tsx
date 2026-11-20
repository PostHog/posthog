import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'
import { Button, Item, ItemActions, ItemContent, ItemDescription, ItemTitle, Switch, Text } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { ErrorTrackingBuiltInFilterApi } from '../../../generated/api.schemas'

export interface BuiltInFilterRowProps {
    filter: ErrorTrackingBuiltInFilterApi
    saving: boolean
    editDisabledReason: string | null
    onSetEnabled: (enabled: boolean) => void
}

export function BuiltInFilterRow({
    filter,
    saving,
    editDisabledReason,
    onSetEnabled,
}: BuiltInFilterRowProps): JSX.Element {
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <Item size="sm" variant="outline">
                <ItemContent className="min-w-0">
                    <ItemTitle>{filter.name}</ItemTitle>
                    <ItemDescription>{filter.description}</ItemDescription>
                    {filter.disabled_reason ? (
                        <Text size="xs" variant="destructive" render={<p className="m-0" />}>
                            <span>Ingestion turned this rule off after it failed on an event: </span>
                            <span translate="no">{filter.disabled_reason}</span>
                        </Text>
                    ) : null}
                </ItemContent>
                <ItemActions className="flex-wrap justify-end">
                    {filter.disabled_reason ? (
                        <Button
                            variant="outline"
                            loading={saving}
                            disabledReason={editDisabledReason}
                            onClick={() => onSetEnabled(true)}
                            data-attr="error-tracking-built-in-filter-retry"
                        >
                            Retry
                        </Button>
                    ) : null}
                    <Switch
                        checked={filter.enabled}
                        onCheckedChange={onSetEnabled}
                        disabled={saving}
                        disabledReason={editDisabledReason}
                        aria-label={filter.name}
                        data-attr={`error-tracking-built-in-filter-${filter.key}`}
                    />
                </ItemActions>
            </Item>
        )
    }

    return (
        <div className="flex items-center gap-4 p-3">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <span className="font-semibold">{filter.name}</span>
                <span className="text-secondary">{filter.description}</span>
                {filter.disabled_reason ? (
                    <span className="text-danger text-xs">
                        <span>Ingestion turned this rule off after it failed on an event: </span>
                        <span translate="no">{filter.disabled_reason}</span>
                    </span>
                ) : null}
            </div>
            {filter.disabled_reason ? (
                <LemonButton
                    type="secondary"
                    size="small"
                    loading={saving}
                    disabledReason={editDisabledReason}
                    onClick={() => onSetEnabled(true)}
                    data-attr="error-tracking-built-in-filter-retry"
                >
                    Retry
                </LemonButton>
            ) : null}
            <LemonSwitch
                checked={filter.enabled}
                onChange={onSetEnabled}
                loading={saving}
                disabledReason={editDisabledReason}
                aria-label={filter.name}
                data-attr={`error-tracking-built-in-filter-${filter.key}`}
            />
        </div>
    )
}
