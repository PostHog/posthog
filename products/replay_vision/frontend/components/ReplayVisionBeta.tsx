import { useActions } from 'kea'

import * as xRayPng from '@posthog/brand/hoggies/png/x-ray'
import { LemonButton } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { supportLogic } from 'lib/components/Support/supportLogic'

const HedgehogXRay = pngHoggie(xRayPng)

/**
 * Replay vision is gated on an allowlist rather than a rollout, so an off flag means "you can't have
 * this yet", not "this page doesn't exist". Showing a 404 instead dead-ended anyone following a link
 * shared by a teammate who is on the beta.
 */
export function ReplayVisionBeta(): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)

    return (
        <div className="flex flex-col items-center gap-3 py-16 text-center">
            <HedgehogXRay className="w-40" />
            <h2 className="mb-0 text-xl font-semibold">Replay vision is in beta</h2>
            <p className="max-w-120 mb-0 text-secondary">
                We're testing it with a small group of teams first. Ask us to add yours and we'll let you know when
                you're in.
            </p>
            <LemonButton
                type="primary"
                onClick={() => openSupportForm({ kind: 'support', target_area: 'session_replay' })}
            >
                Request access
            </LemonButton>
        </div>
    )
}
