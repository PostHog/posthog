import { useActions, useValues } from 'kea'

import { LemonBanner, LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { suggestionActionLogic } from '../logics/suggestionActionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { ALERT_DIRECTION_OPTIONS } from '../utils/turnSuggestions'
import { SlackDestinationSection } from './SlackDestinationSection'
import { SuggestionActionRow } from './SuggestionActionRow'
import { SuggestionDraftSummary } from './SuggestionDraftSummary'

export function AlertSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = suggestionActionLogic(props)
    const { suggestion, direction, changePercent, accepted, slackChannelLabel } = useValues(logic)
    const { setDirection, setChangePercent } = useActions(logic)

    if (suggestion?.kind !== 'alert') {
        return null
    }
    if (accepted) {
        return (
            <LemonBanner
                type={accepted.slackConnected ? 'success' : 'warning'}
                action={accepted.url ? { to: accepted.url, children: 'View alert' } : undefined}
            >
                {accepted.slackConnected
                    ? `Alert created. It checks ${suggestion.alert.insightName} once a day and posts to ${slackChannelLabel}.`
                    : `Alert created, but it can't post to ${slackChannelLabel} yet. Open the alert to add Slack.`}
            </LemonBanner>
        )
    }

    return (
        <>
            <SuggestionDraftSummary name={suggestion.alert.insightName} />

            <div className="flex flex-wrap items-end gap-2">
                <div className="flex flex-col gap-1">
                    <LemonLabel>Fires when it</LemonLabel>
                    <LemonSelect
                        size="small"
                        value={direction}
                        options={ALERT_DIRECTION_OPTIONS}
                        onChange={(value) => value && setDirection(value)}
                    />
                </div>
                <div className="flex flex-col gap-1">
                    <LemonLabel>More than</LemonLabel>
                    <LemonInput
                        size="small"
                        type="number"
                        min={1}
                        step={1}
                        suffix={<span className="text-secondary">%</span>}
                        value={changePercent}
                        onChange={(value) => setChangePercent(value ?? 0)}
                        className="w-24"
                        data-attr="posthog-ai-turn-suggestion-alert-percent"
                    />
                </div>
            </div>

            <SlackDestinationSection {...props} connectHint="Connect Slack to post the alert to a channel." />

            <SuggestionActionRow
                {...props}
                label="Create alert"
                dataAttr="posthog-ai-turn-suggestion-create-alert"
                failedMessage="Couldn't create the alert. Try again."
            />
        </>
    )
}
