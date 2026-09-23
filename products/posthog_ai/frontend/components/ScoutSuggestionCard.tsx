import { useActions, useValues } from 'kea'

import { LemonBanner, LemonLabel, LemonSelect, Link } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { CADENCE_OPTIONS, SCOUT_MODE_HINTS, cadenceLabel } from '../utils/turnSuggestions'
import { SlackDestinationSection } from './SlackDestinationSection'
import { SuggestionActionRow } from './SuggestionActionRow'
import { SuggestionDraftSummary } from './SuggestionDraftSummary'

export function ScoutSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = suggestionActionLogic(props)
    const { suggestion, cadence, accepted, slackChannelLabel } = useValues(logic)
    const { setCadence } = useActions(logic)

    if (suggestion?.kind !== 'scout') {
        return null
    }
    if (accepted) {
        return (
            <LemonBanner
                type="success"
                action={accepted.url ? { to: accepted.url, children: 'View scout' } : undefined}
            >
                Scout created. It runs {cadenceLabel(cadence)} and posts to {slackChannelLabel}.
            </LemonBanner>
        )
    }
    const modeHint = SCOUT_MODE_HINTS[suggestion.scout.mode]

    return (
        <>
            <SuggestionDraftSummary name={suggestion.scout.displayName}>
                {suggestion.scout.description && (
                    <span className="text-xs text-secondary">{suggestion.scout.description}</span>
                )}
                {modeHint && <span className="text-xs text-secondary">{modeHint}</span>}
            </SuggestionDraftSummary>

            <div className="flex flex-col gap-1">
                <LemonLabel>Runs</LemonLabel>
                <LemonSelect
                    size="small"
                    value={cadence}
                    options={CADENCE_OPTIONS}
                    onChange={(value) => value && setCadence(value)}
                />
            </div>

            <SlackDestinationSection {...props} connectHint="Connect Slack to post each run to a channel." />

            <SuggestionActionRow
                {...props}
                label="Create scout"
                dataAttr="posthog-ai-turn-suggestion-create-scout"
                failedMessage={
                    <>
                        Couldn't create the scout. Try again, or create it from the <Link to={urls.inbox()}>inbox</Link>
                        .
                    </>
                }
            />
        </>
    )
}
