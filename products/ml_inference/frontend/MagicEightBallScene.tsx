import './MagicEightBall.scss'

import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect, useRef } from 'react'

import { LemonButton, LemonInput, Spinner } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { appLogic } from 'scenes/appLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'

import { magicEightBallLogic } from './magicEightBallLogic'

export const scene: SceneExport = {
    component: MagicEightBallScene,
    logic: magicEightBallLogic,
}

// accelerationIncludingGravity sits near 9.8 at rest; a deliberate shake goes well past this.
const SHAKE_THRESHOLD = 25
// One shake is a burst of force peaks. The detector rearms only after the force stays below the threshold this long.
const SHAKE_QUIET_MS = 1000
const HAZY_ANSWER = 'Reply hazy, try again'

function useShake(onShake: () => void, enabled: boolean): void {
    const onShakeRef = useRef(onShake)
    onShakeRef.current = onShake

    useEffect(() => {
        if (!enabled) {
            return
        }
        let armed = true
        let lastPeak = 0
        const handleMotion = (event: DeviceMotionEvent): void => {
            const acceleration = event.accelerationIncludingGravity
            if (!acceleration) {
                return
            }
            const { x, y, z } = acceleration
            const force = Math.sqrt((x ?? 0) ** 2 + (y ?? 0) ** 2 + (z ?? 0) ** 2)
            const now = Date.now()
            if (force > SHAKE_THRESHOLD) {
                lastPeak = now
                if (armed) {
                    armed = false
                    onShakeRef.current()
                }
            } else if (now - lastPeak > SHAKE_QUIET_MS) {
                armed = true
            }
        }
        window.addEventListener('devicemotion', handleMotion)
        return () => window.removeEventListener('devicemotion', handleMotion)
    }, [enabled])
}

export function MagicEightBallScene(): JSX.Element {
    const { featureFlags, receivedFeatureFlags } = useValues(featureFlagLogic)
    const { preflight } = useValues(preflightLogic)
    const { featureFlagsTimedOut } = useValues(appLogic)

    // Same gate as the decisions playground: the flag enrols a project, and local development needs no flag.
    if (!featureFlags[FEATURE_FLAGS.ML_INFERENCE_DECISIONS] && !preflight?.is_debug) {
        return receivedFeatureFlags || featureFlagsTimedOut ? (
            <NotFound object="page" />
        ) : (
            <Spinner className="text-3xl mx-auto my-8" />
        )
    }

    return <MagicEightBall />
}

function MagicEightBall(): JSX.Element {
    const { question, answer, confidence, askError, decisionLoading, askDisabledReason, motionAllowed } =
        useValues(magicEightBallLogic)
    const { setQuestion, ask, requestMotionPermission } = useActions(magicEightBallLogic)

    const tryAsk = (): void => {
        if (!askDisabledReason) {
            ask()
        }
    }
    useShake(tryAsk, motionAllowed)

    const reveal = askError ? HAZY_ANSWER : answer

    return (
        <SceneContent>
            <SceneTitleSection
                name="Magic 8 ball"
                description="Ask a product question. The decision model picks the ball's answer."
                resourceType={{ type: 'ml_inference' }}
            />
            <div className="flex flex-col items-center gap-6 py-6">
                <div className="w-full max-w-xl">
                    <LemonInput
                        value={question}
                        onChange={setQuestion}
                        onPressEnter={tryAsk}
                        placeholder="Will the new onboarding flow lift activation?"
                        autoFocus
                        fullWidth
                        data-attr="magic-eight-ball-question"
                    />
                </div>
                <button
                    type="button"
                    className={clsx('MagicEightBall', decisionLoading && 'MagicEightBall--shaking')}
                    onClick={tryAsk}
                    aria-label="Shake the magic 8 ball"
                    aria-busy={decisionLoading}
                    data-attr="magic-eight-ball"
                >
                    <div className="MagicEightBall__window">
                        {decisionLoading ? null : reveal ? (
                            <div className="MagicEightBall__triangle">
                                <span>{reveal}</span>
                            </div>
                        ) : (
                            <div className="MagicEightBall__eight">8</div>
                        )}
                    </div>
                </button>
                {/* The button's aria-label hides the answer inside it, so screen readers get it here. */}
                <span role="status" className="sr-only">
                    {decisionLoading ? null : reveal}
                </span>
                <p className="text-secondary text-center m-0">
                    {askError
                        ? `The model didn't answer: ${askError}`
                        : answer && confidence !== null && !decisionLoading
                          ? `The ball was ${Math.round(confidence * 100)}% sure.`
                          : 'Type a question, then shake your phone, tap the ball or press Enter.'}
                </p>
                {!motionAllowed && (
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => requestMotionPermission()}
                        data-attr="magic-eight-ball-motion"
                    >
                        Enable shake to ask
                    </LemonButton>
                )}
            </div>
        </SceneContent>
    )
}
