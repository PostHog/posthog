import {
    Badge,
    Button,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemTitle,
    Switch,
    Text,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

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
        <Item variant="outline" tone={filter.disabled_reason ? 'warning' : 'default'}>
            <ItemContent>
                <ItemTitle>
                    {filter.name}
                    <Tooltip>
                        <TooltipTrigger render={<span className="inline-flex" />}>
                            <Badge>{evaluation.label}</Badge>
                        </TooltipTrigger>
                        <TooltipContent>{evaluation.tooltip}</TooltipContent>
                    </Tooltip>
                </ItemTitle>
                <ItemDescription>{filter.description}</ItemDescription>
                {filter.disabled_reason ? (
                    <Text size="xs" variant="destructive" className="m-0">
                        <span>Ingestion turned this rule off after it failed on an event: </span>
                        <span translate="no">{filter.disabled_reason}</span>
                    </Text>
                ) : null}
            </ItemContent>
            <ItemActions>
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
                    onCheckedChange={(checked) => onSetEnabled(checked)}
                    disabledReason={editDisabledReason ?? (saving ? 'Saving…' : undefined)}
                    aria-label={filter.name}
                    data-attr={`error-tracking-built-in-filter-${filter.key}`}
                />
            </ItemActions>
        </Item>
    )
}
