import { useActions, useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'
import { preflightLogic } from 'lib/logic/preflightLogic'
import posthog from 'lib/posthog-typed'

// The support ticket carries only the message, so the model-request topic lives in the prefill.
export const REQUEST_MODEL_MESSAGE =
    'Model request for Replay vision:\n\nWhich model would you like to use for scanners, and why?\n\n'

/** Inline CTA under the scanner model select, so users can tell us which model to support next. */
export function RequestModelButton(): JSX.Element | null {
    const { openSupportForm } = useActions(supportLogic)
    const { preflight } = useValues(preflightLogic)

    // Self-hosted instances have no support channel, so the CTA would dead-end there.
    if (!preflight?.cloud) {
        return null
    }

    return (
        <span>
            Missing a model?{' '}
            <Link
                data-attr="vision-request-model"
                onClick={() => {
                    posthog.capture('replay_vision_model_request_clicked')
                    openSupportForm({ kind: 'feedback', isEmailFormOpen: true, message: REQUEST_MODEL_MESSAGE })
                }}
            >
                Request a model
            </Link>
        </span>
    )
}
