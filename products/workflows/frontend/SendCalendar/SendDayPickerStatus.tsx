import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
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
            <LemonBanner type="info">
                Transactional emails don't count toward the frequency cap, so any day works.
            </LemonBanner>
        )
    }
    if (sendAt && !selectedCrowding.length) {
        return <LemonBanner type="success">This time stays within {describeRule(rule)}.</LemonBanner>
    }

    const suggestionLabel = suggestion?.tz(effectiveTimezone).format('ddd, MMM D [at] h:mm A')
    const action = suggestion
        ? {
              children: 'Use this day',
              onClick: applySuggestion,
              'data-attr': 'send-day-picker-use-suggestion',
          }
        : undefined
    const suggestionText = suggestion ? (
        <>
            The first day that keeps to {describeRule(rule)} is <strong>{suggestionLabel}</strong>.
        </>
    ) : (
        <>
            No day in the next {SUGGESTION_HORIZON_DAYS} days keeps to {describeRule(rule)}.
        </>
    )

    if (sendAt) {
        const names = [...new Set(selectedCrowding.map((send) => send.name))].join(', ')
        return (
            <LemonBanner type="warning" action={action}>
                Some people in this audience also get {names} within {rule.windowDays}{' '}
                {rule.windowDays === 1 ? 'day' : 'days'}. {suggestionText}
            </LemonBanner>
        )
    }
    return (
        <LemonBanner type="info" action={action}>
            {suggestionText}
        </LemonBanner>
    )
}
