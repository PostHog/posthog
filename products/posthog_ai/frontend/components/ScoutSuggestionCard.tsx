import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonLabel, LemonSelect, Link } from '@posthog/lemon-ui'

import { slackChannelDisplayName } from 'lib/integrations/slackChannel'
import { urls } from 'scenes/urls'

import { scoutSuggestionLogic } from '../logics/scoutSuggestionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { CADENCE_OPTIONS, SCOUT_MODE_HINTS, cadenceLabel } from '../utils/turnSuggestions'
import { SlackDestinationSection } from './SlackDestinationSection'

export function ScoutSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = scoutSuggestionLogic(props)
    const {
        suggestion,
        cadence,
        slackChannel,
        createdScout,
        createdScoutLoading,
        createDisabledReason,
        createError,
        scoutUrl,
    } = useValues(logic)
    const { setCadence, createScout } = useActions(logic)

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
    const modeHint = SCOUT_MODE_HINTS[suggestion.scout.mode]

    return (
        <>
            <div className="flex flex-col gap-0.5 rounded bg-surface-secondary px-2 py-1.5">
                <span className="text-sm font-medium">{suggestion.scout.displayName}</span>
                {suggestion.scout.description && (
                    <span className="text-xs text-secondary">{suggestion.scout.description}</span>
                )}
                {modeHint && <span className="text-xs text-secondary">{modeHint}</span>}
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

            <SlackDestinationSection {...props} connectHint="Connect Slack to get each run posted to a channel." />

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
