import { LemonBanner, LemonSkeleton } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonRadio, LemonRadioOption } from 'lib/lemon-ui/LemonRadio'

import { IntegrationType } from '~/types'

import type { LinearTeamsScope } from '../../logics/linearTeamsModalLogic'
import { LinearTeamsSelect } from './LinearTeamsSelect'

const SCOPE_OPTIONS: LemonRadioOption<LinearTeamsScope>[] = [
    { value: 'all', label: 'All teams', 'data-attr': 'signal-source-filter-teams-all' },
    { value: 'selected', label: 'Only the teams I pick', 'data-attr': 'signal-source-filter-teams-selected' },
]

export interface SourceFilterLinearTeamsProps {
    /** The form's current scope, which decides whether the team picker shows. */
    scope: LinearTeamsScope
    linearIntegration: IntegrationType | null
    integrationsUnknown: boolean
    integrationsLoadFailed: boolean
    onRetryIntegrations: () => void
    disabledReason?: string
}

/** The Linear teams part of the filter editor. Must render inside the editor's form. */
export function SourceFilterLinearTeams({
    scope,
    linearIntegration,
    integrationsUnknown,
    integrationsLoadFailed,
    onRetryIntegrations,
    disabledReason,
}: SourceFilterLinearTeamsProps): JSX.Element {
    // A radio group disables per option, so the reason goes on each one.
    const options = disabledReason ? SCOPE_OPTIONS.map((option) => ({ ...option, disabledReason })) : SCOPE_OPTIONS
    return (
        <div className="flex flex-col gap-2">
            <LemonField name="teamScope" label="Teams">
                {({ value, onChange }) => (
                    <LemonRadio
                        value={value}
                        onChange={onChange}
                        options={options}
                        aria-label="Which Linear teams to read"
                    />
                )}
            </LemonField>
            {scope === 'selected' &&
                (integrationsLoadFailed && integrationsUnknown ? (
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
                ) : integrationsUnknown ? (
                    <LemonSkeleton className="h-10" />
                ) : linearIntegration ? (
                    <LemonField name="teamIds">
                        <LinearTeamsSelect integrationId={linearIntegration.id} disabled={!!disabledReason} />
                    </LemonField>
                ) : (
                    <LemonBanner type="warning">
                        Couldn't find your Linear connection, so the team list isn't available. Reconnect Linear in
                        integration settings, then try again.
                    </LemonBanner>
                ))}
        </div>
    )
}
