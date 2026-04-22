import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonButton, LemonSwitch } from '@posthog/lemon-ui'

import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { DisableSurvey } from './DisableSurvey'
import { disableSurveyLogic } from './disableSurveyLogic'
import { testExceptionLogic } from './testExceptionLogic'

export function ExceptionAutocaptureToggle(): JSX.Element {
    const { userLoading } = useValues(userLogic)
    const { currentTeam } = useValues(teamLogic)
    const { updateCurrentTeam, addProductIntent } = useActions(teamLogic)
    const { reportAutocaptureExceptionsToggled } = useActions(eventUsageLogic)
    const { showSurvey, hideSurvey } = useActions(disableSurveyLogic)

    return (
        <>
            <LemonSwitch
                id="posthog-autocapture-exceptions-switch"
                onChange={(checked) => {
                    if (checked) {
                        addProductIntent({
                            product_type: ProductKey.ERROR_TRACKING,
                            intent_context: ProductIntentContext.ERROR_TRACKING_EXCEPTION_AUTOCAPTURE_ENABLED,
                        })
                    }
                    updateCurrentTeam({
                        autocapture_exceptions_opt_in: checked,
                    })
                    reportAutocaptureExceptionsToggled(checked)
                    if (checked) {
                        hideSurvey()
                    } else {
                        showSurvey()
                    }
                }}
                checked={!!currentTeam?.autocapture_exceptions_opt_in}
                disabled={userLoading}
                label="Enable exception autocapture"
                bordered
            />
            <TestExceptionButton />
            <DisableSurvey />
        </>
    )
}

function TestExceptionButton(): JSX.Element {
    const { status } = useValues(testExceptionLogic)
    const { sendTestException, reset } = useActions(testExceptionLogic)

    const waiting = status === 'waiting'

    return (
        <div className="flex flex-col gap-2 mt-2">
            <div className="flex items-center gap-2 flex-wrap">
                <LemonButton
                    type="secondary"
                    size="small"
                    loading={waiting}
                    disabledReason={waiting ? 'Waiting for the exception to arrive…' : undefined}
                    onClick={() => sendTestException()}
                >
                    {status === 'received' || status === 'timeout'
                        ? 'Send another test exception'
                        : 'Send a test exception'}
                </LemonButton>
                <span className="text-secondary text-xs">
                    Fires <code>posthog.captureException</code> from this page to verify the pipeline end-to-end.
                </span>
            </div>
            <TestExceptionStatus />
            {(status === 'received' || status === 'timeout') && (
                <LemonButton size="xsmall" type="tertiary" onClick={() => reset()}>
                    Clear result
                </LemonButton>
            )}
        </div>
    )
}

function TestExceptionStatus(): JSX.Element | null {
    const { status } = useValues(testExceptionLogic)

    if (status === 'idle') {
        return null
    }

    if (status === 'waiting') {
        return <span className="text-secondary text-sm">Test exception sent. Waiting for it to arrive in PostHog…</span>
    }

    if (status === 'received') {
        return (
            <span className="text-success text-sm inline-flex items-center gap-1">
                <IconCheckCircle className="text-base" />
                Received your test exception — autocapture is working.
            </span>
        )
    }

    return (
        <span className="text-warning text-sm inline-flex items-center gap-1">
            <IconWarning className="text-base" />
            No exception event seen yet. Check that the SDK is initialized and that an ad blocker isn't dropping
            requests.
        </span>
    )
}
