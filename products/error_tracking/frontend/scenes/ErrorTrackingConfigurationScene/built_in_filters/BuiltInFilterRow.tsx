import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

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
