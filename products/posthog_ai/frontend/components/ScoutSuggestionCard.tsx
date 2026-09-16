import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonLabel, LemonSelect, Link } from '@posthog/lemon-ui'

import api from 'lib/api'
import { SlackDestinationPicker } from 'lib/components/Comments/SlackDestinationPicker'
import { slackChannelDisplayName } from 'lib/integrations/slackChannel'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { urls } from 'scenes/urls'

import { scoutSuggestionLogic } from '../logics/scoutSuggestionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { CADENCE_OPTIONS, cadenceLabel } from '../utils/turnSuggestions'

export function ScoutSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = scoutSuggestionLogic(props)
    const {
        suggestion,
        cadence,
        slackIntegrationId,
        slackChannel,
        slackIntegrations,
        integrationsLoading,
        createdScout,
        createdScoutLoading,
        createDisabledReason,
        createError,
        waitingForSlack,
        scoutUrl,
    } = useValues(logic)
    const { setCadence, setSlackIntegrationId, setSlackChannel, connectSlackClicked, createScout } = useActions(logic)

    if (!suggestion) {
        return null
    }
    if (createdScout) {
        return (
            <LemonBanner type="success" action={scoutUrl ? { to: scoutUrl, children: 'View scout' } : undefined}>
                Scout created. It runs {cadenceLabel(cadence)} and posts to{' '}
                {slackChannel ? slackChannelDisplayName(slackChannel) : 'Slack'}.
            </LemonBanner>
        )
    }

    const hasSlackWorkspace = !!slackIntegrations?.length
    const slackWorkspacesLoading = integrationsLoading && !hasSlackWorkspace

    return (
        <>
            <div className="flex flex-col gap-0.5 rounded bg-surface-secondary px-2 py-1.5">
                <span className="text-sm font-medium">{suggestion.scout.displayName}</span>
                {suggestion.scout.description && (
                    <span className="text-xs text-secondary">{suggestion.scout.description}</span>
                )}
            </div>

            <div className="flex flex-col gap-1">
                <LemonLabel>Runs</LemonLabel>
                <LemonSelect
                    size="small"
                    value={cadence}
                    options={CADENCE_OPTIONS}
                    onChange={(value) => value && setCadence(value)}
                />
            </div>

            {slackWorkspacesLoading ? (
                <div className="flex justify-center p-2">
                    <Spinner />
                </div>
            ) : hasSlackWorkspace ? (
                <SlackDestinationPicker
                    integrationId={slackIntegrationId}
                    channel={slackChannel}
                    onIntegrationChange={setSlackIntegrationId}
                    onChannelChange={setSlackChannel}
                />
            ) : (
                <div className="flex flex-col gap-2">
                    <span className="text-sm text-secondary">
                        Connect Slack to get each run posted to a channel. It opens in a new tab, and this card updates
                        when you come back.
                    </span>
                    <div className="flex items-center gap-2">
                        <LemonButton
                            type="secondary"
                            size="small"
                            to={api.integrations.authorizeUrl({
                                kind: 'slack',
                                next: urls.settings('project-integrations'),
                            })}
                            targetBlank
                            disableClientSideRouting
                            onClick={connectSlackClicked}
                            data-attr="posthog-ai-turn-suggestion-connect-slack"
                        >
                            Connect Slack
                        </LemonButton>
                        {waitingForSlack && (
                            <span className="flex items-center gap-1 text-xs text-secondary">
                                <Spinner className="text-sm" />
                                Waiting for Slack
                            </span>
                        )}
                    </div>
                </div>
            )}

            {createError && (
                <LemonBanner type="error">
                    Couldn't create the scout. Try again, or create it from the <Link to={urls.inbox()}>inbox</Link>.
                </LemonBanner>
            )}

            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={createScout}
                    loading={createdScoutLoading}
                    disabledReason={createDisabledReason ?? undefined}
                    data-attr="posthog-ai-turn-suggestion-create-scout"
                >
                    Create scout
                </LemonButton>
            </div>
        </>
    )
}
