import { useActions, useMountedLogic, useValues } from 'kea'

import { IconCheck, IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { Spinner } from 'lib/lemon-ui/Spinner'

import { broadcastWizardLogic } from '../Broadcasts/broadcastWizardLogic'
import { sendDayPickerLogic } from './sendDayPickerLogic'
import { SUGGESTION_HORIZON_DAYS, describeRule } from './sendSpacing'

export function SendDayPickerStatus(): JSX.Element {
    const { props } = useMountedLogic(broadcastWizardLogic)
    const { scheduledFlows, sendAt, selectedCrowding, suggestion, rule, isTransactional, effectiveTimezone } =
        useValues(sendDayPickerLogic(props))
    const { applySuggestion } = useActions(sendDayPickerLogic(props))

    if (!scheduledFlows) {
        return (
            <div className="flex items-center gap-2 text-sm text-secondary">
                <Spinner /> Checking your other sends…
            </div>
        )
    }
    if (isTransactional) {
        return (
            <div className="text-sm text-secondary">
                Transactional emails don't count toward the frequency cap, so any day works.
            </div>
        )
    }
    if (sendAt && !selectedCrowding.length) {
        return (
            <div className="flex items-center gap-1 text-sm">
                <IconCheck className="shrink-0 text-success" />
                This time stays within {describeRule(rule)}.
            </div>
        )
    }
    const names = [...new Set(selectedCrowding.map((send) => send.name))].join(', ')
    return (
        <div className="flex flex-col gap-1 text-sm">
            {sendAt ? (
                <div className="flex items-start gap-1 text-warning">
                    <IconWarning className="mt-0.5 shrink-0" />
                    <span>
                        Some people in this audience also get {names} within {rule.windowDays}{' '}
                        {rule.windowDays === 1 ? 'day' : 'days'}. That's more than {describeRule(rule)}.
                    </span>
                </div>
            ) : null}
            {suggestion ? (
                <div className="flex flex-wrap items-center gap-2">
                    <span>
                        Suggested: <strong>{suggestion.tz(effectiveTimezone).format('ddd, MMM D [at] h:mm A')}</strong>
                    </span>
                    <LemonButton
                        type="secondary"
                        size="xsmall"
                        onClick={applySuggestion}
                        data-attr="send-day-picker-use-suggestion"
                    >
                        Use this day
                    </LemonButton>
                </div>
            ) : (
                <span className="text-secondary">
                    No day in the next {SUGGESTION_HORIZON_DAYS} days stays within {describeRule(rule)}.
                </span>
            )}
        </div>
    )
}
