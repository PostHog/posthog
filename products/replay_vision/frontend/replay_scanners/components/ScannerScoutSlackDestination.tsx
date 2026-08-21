import { useValues } from 'kea'

import { IntegrationChoice } from 'lib/components/CyclotronJob/integrations/IntegrationChoice'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { SlackChannelPicker, SlackNotConfiguredBanner } from 'lib/integrations/SlackIntegrationHelpers'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner'

import type { SignalScoutOutputDestinationsApi } from 'products/signals/frontend/generated/api.schemas'

// Styled like the legacy action editor's Slack delivery section (workspace choice + labeled channel
// picker), writing the scout config's destination shape instead of a vision action's delivery_config.
export function ScannerScoutSlackDestination({
    destinations,
    onChange,
}: {
    destinations?: SignalScoutOutputDestinationsApi | null
    onChange: (outputDestinations: SignalScoutOutputDestinationsApi) => void
}): JSX.Element {
    // This control owns the `slack` key only. It carries the rest through, because
    // `output_destinations` also holds the webhook destination this scout provisioned, and replacing
    // the object would drop that pointer while the destination kept delivering.
    const destination = destinations?.slack
    const withSlack = (slack: SignalScoutOutputDestinationsApi['slack'] | undefined): void =>
        onChange(slack ? { ...destinations, slack } : { ...destinations, slack: null })
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const header = <span className="text-xs text-default">Slack</span>

    if (!slackIntegrations?.length) {
        // Don't flash the "add to Slack" banner (which also builds an authorize URL) while the
        // integrations list is still loading.
        if (integrationsLoading) {
            return <Spinner />
        }
        return (
            <div className="flex flex-col gap-2">
                {header}
                <SlackNotConfiguredBanner />
            </div>
        )
    }

    const selectedIntegration = slackIntegrations.find((i) => i.id === destination?.integration_id)

    return (
        <div className="flex flex-col gap-2">
            {header}
            <IntegrationChoice
                integration="slack"
                value={destination?.integration_id ?? undefined}
                onChange={(value) => withSlack(value ? { integration_id: value as number, channel: null } : undefined)}
            />
            {selectedIntegration && (
                <LemonField.Pure label="Channel">
                    <SlackChannelPicker
                        integration={selectedIntegration}
                        value={destination?.channel ?? undefined}
                        // Clearing the channel drops the whole destination rather than persisting a
                        // workspace with no channel, which is what the Inbox's control stores too.
                        onChange={(next) =>
                            withSlack(next ? { integration_id: selectedIntegration.id, channel: next } : undefined)
                        }
                    />
                </LemonField.Pure>
            )}
            {!destination?.channel && (
                <span className="text-[11.5px] text-muted">Leave the channel empty for no Slack message.</span>
            )}
        </div>
    )
}
