import { useValues } from 'kea'
import { useState } from 'react'

import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import { BroadcastPerformanceLogicProps, broadcastPerformanceLogic } from './broadcastPerformanceLogic'
import { BroadcastSendError, findMergeTag } from './broadcastSendError'

export interface BroadcastSendErrorAction {
    label: string
    onClick: () => void
}

/** Sending again goes to the whole audience, so a sender has to know when that repeats the email for some people. */
function sendAgainStep(sent: number, noun: string): string {
    if (sent === 0) {
        return 'Send it again to reach them.'
    }
    return `Sending it again goes to the whole audience, including the ${humanFriendlyNumber(sent)} ${
        sent === 1 ? 'person' : 'people'
    } who got this ${noun}.`
}

function actionFor(
    sendError: BroadcastSendError | null,
    fixAction: BroadcastSendErrorAction | undefined,
    resendAction: BroadcastSendErrorAction | undefined
): BroadcastSendErrorAction | undefined {
    if (sendError?.kind === 'content') {
        return fixAction
    }
    if (sendError?.kind === 'our_side') {
        return resendAction
    }
    return undefined
}

function SendErrorReason({
    sendError,
    tag,
    nextStep,
}: {
    sendError: BroadcastSendError | null
    tag: string | null
    nextStep: string
}): JSX.Element {
    if (!sendError) {
        return <span>Sending it hit an error.</span>
    }
    return (
        <span>
            {tag ? (
                <>
                    {`${sendError.reason}: `}
                    <code translate="no">{tag}</code>
                    {'. '}
                </>
            ) : (
                `${sendError.reason}. `
            )}
            {nextStep}
        </span>
    )
}

function ErrorLogDetails({ log }: { log: string }): JSX.Element {
    const [showDetails, setShowDetails] = useState(false)
    return (
        <>
            <LemonButton
                size="xsmall"
                type="tertiary"
                noPadding
                sideIcon={showDetails ? <IconChevronDown /> : <IconChevronRight />}
                onClick={() => setShowDetails(!showDetails)}
                data-attr="broadcast-send-error-details"
            >
                {showDetails ? 'Hide details' : 'Show details'}
            </LemonButton>
            {showDetails ? (
                <code className="block w-full whitespace-pre-wrap wrap-anywhere text-xs" translate="no">
                    {log}
                </code>
            ) : null}
        </>
    )
}

/** Says why people in a run got nothing, for a run whose sends errored before they reached the provider. */
export function BroadcastSendErrorBanner({
    fixAction,
    resendAction,
    content,
    ...props
}: BroadcastPerformanceLogicProps & {
    fixAction?: BroadcastSendErrorAction
    resendAction?: BroadcastSendErrorAction
    /** The text the sender wrote, used to show a merge tag in full when the log cut it off. */
    content?: string
}): JSX.Element | null {
    const { sendCounts, sendError, latestErrorLog } = useValues(broadcastPerformanceLogic(props))

    const notSent = sendCounts?.notSent ?? 0
    if (notSent === 0) {
        return null
    }
    const noun = props.channel === 'push' ? 'notification' : 'email'
    const tag = sendError?.tag && content ? findMergeTag(sendError.tag, content) : (sendError?.tag ?? null)
    const nextStep = sendError?.nextStep ?? sendAgainStep(sendCounts?.sent ?? 0, noun)
    const action = actionFor(sendError, fixAction, resendAction)

    return (
        <LemonBanner
            type="error"
            alignItems="start"
            action={
                action
                    ? { children: action.label, onClick: action.onClick, 'data-attr': 'broadcast-send-error-action' }
                    : undefined
            }
        >
            <div className="flex flex-col items-start gap-1" data-attr="broadcast-send-error">
                <span className="wrap-anywhere">
                    <span className="font-semibold">{`${humanFriendlyNumber(notSent)} ${
                        notSent === 1 ? 'person' : 'people'
                    } didn't get this ${noun}.`}</span>{' '}
                    <SendErrorReason sendError={sendError} tag={tag} nextStep={nextStep} />
                </span>
                {latestErrorLog ? <ErrorLogDetails log={latestErrorLog} /> : null}
            </div>
        </LemonBanner>
    )
}
