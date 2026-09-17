import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonInput, LemonLabel, LemonSelect } from '@posthog/lemon-ui'

import { slackChannelDisplayName } from 'lib/integrations/slackChannel'

import { alertSuggestionLogic } from '../logics/alertSuggestionLogic'
import type { TurnSuggestionLogicProps } from '../logics/turnSuggestionLogic'
import { ALERT_DIRECTION_OPTIONS } from '../utils/turnSuggestions'
import { SlackDestinationSection } from './SlackDestinationSection'

export function AlertSuggestionCard(props: TurnSuggestionLogicProps): JSX.Element | null {
    const logic = alertSuggestionLogic(props)
    const {
        suggestion,
        direction,
        changePercent,
        slackChannel,
        createdAlert,
        createdAlertLoading,
        createDisabledReason,
        createError,
        alertUrl,
    } = useValues(logic)
    const { setDirection, setChangePercent, createAlert } = useActions(logic)

    if (!suggestion) {
        return null
    }
    if (createdAlert) {
        const channel = slackChannel ? slackChannelDisplayName(slackChannel) : 'Slack'
        return (
            <LemonBanner
                type={createdAlert.slackConnected ? 'success' : 'warning'}
                action={alertUrl ? { to: alertUrl, children: 'View alert' } : undefined}
            >
                {createdAlert.slackConnected
                    ? `Alert created. It checks ${suggestion.alert.insightName} daily and posts to ${channel}.`
                    : `Alert created, but ${channel} could not be added. Add the Slack destination from the alert.`}
            </LemonBanner>
        )
    }

    return (
        <>
            <div className="flex flex-col gap-0.5 rounded bg-surface-secondary px-2 py-1.5">
                <span className="text-sm font-medium">{suggestion.alert.insightName}</span>
                <span className="text-xs text-secondary">
                    Checked daily against the previous day. Posts when the change is larger than the bound below.
                </span>
            </div>

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

            <SlackDestinationSection {...props} connectHint="Connect Slack to get the alert posted to a channel." />

            {createError && <LemonBanner type="error">Couldn't create the alert. Try again.</LemonBanner>}

            <div className="flex justify-end">
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={createAlert}
                    loading={createdAlertLoading}
                    disabledReason={createDisabledReason ?? undefined}
                    data-attr="posthog-ai-turn-suggestion-create-alert"
                >
                    Create alert
                </LemonButton>
            </div>
        </>
    )
}
