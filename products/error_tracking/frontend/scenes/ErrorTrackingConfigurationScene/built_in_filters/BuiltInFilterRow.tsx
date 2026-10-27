import { LemonButton, LemonSwitch, LemonTag, Tooltip } from '@posthog/lemon-ui'

import type { ErrorTrackingBuiltInFilterApi } from '../../../generated/api.schemas'

const EVALUATION_LABELS: Record<ErrorTrackingBuiltInFilterApi['evaluation'], { label: string; tooltip: string }> = {
    client: {
        label: 'SDK',
        tooltip:
            'The web SDK drops matching exceptions before it sends them. PostHog also drops matching exceptions from other SDKs during ingestion.',
    },
    server: {
        label: 'Server',
        tooltip: 'PostHog drops matching exceptions during ingestion.',
    },
}

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
    const evaluation = EVALUATION_LABELS[filter.evaluation]

    return (
        <div className="flex items-center gap-4 p-3">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <div className="flex flex-wrap items-center gap-2">
                    <span className="font-semibold">{filter.name}</span>
                    <Tooltip title={evaluation.tooltip}>
                        <LemonTag size="small">{evaluation.label}</LemonTag>
                    </Tooltip>
                </div>
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
