import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { IntegrationType } from '~/types'

import { LinearTeamsSelect } from './LinearTeamsSelect'

export interface SourceFilterLinearTeamsProps {
    linearIntegration: IntegrationType | null
    integrationsUnknown: boolean
    integrationsLoadFailed: boolean
    onRetryIntegrations: () => void
    disabledReason?: string
}

/** The Linear teams part of the filter editor. Must render inside the editor's form. */
export function SourceFilterLinearTeams({
    linearIntegration,
    integrationsUnknown,
    integrationsLoadFailed,
    onRetryIntegrations,
    disabledReason,
}: SourceFilterLinearTeamsProps): JSX.Element {
    if (integrationsUnknown) {
        return integrationsLoadFailed ? (
            <LemonBanner
                type="error"
                action={{
                    children: 'Retry',
                    onClick: onRetryIntegrations,
                    'data-attr': 'signal-source-filter-teams-retry',
                }}
            >
                Couldn't load your Linear connection, so the team list isn't available. Retry to load it.
            </LemonBanner>
        ) : (
            <LemonSkeleton className="h-10" />
        )
    }
    return linearIntegration ? (
        <LemonField name="teamIds" label="Linear teams" help="Leave empty to apply your filter across all teams.">
            <LinearTeamsSelect integrationId={linearIntegration.id} disabled={!!disabledReason} />
        </LemonField>
    ) : (
        <LemonBanner type="warning">
            Couldn't find your Linear connection, so the team list isn't available. Reconnect Linear in integration
            settings, then try again.
        </LemonBanner>
    )
}
