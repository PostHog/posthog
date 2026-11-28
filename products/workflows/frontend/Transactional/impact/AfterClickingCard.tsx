import { BindLogic, useMountedLogic, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { crossSellLinkProps } from '../../workflowsCrossSell'
import { afterClickingScanLogic } from './afterClickingScanLogic'
import { AfterClickingScanPanel } from './AfterClickingScanPanel'
import { emailImpactLogic } from './emailImpactLogic'

export function AfterClickingCard(): JSX.Element | null {
    const impactLogic = useMountedLogic(emailImpactLogic)
    const { replayEnabled, days, linkTagging } = useValues(impactLogic)
    const replayVisionEnabled = useFeatureFlag('WORKFLOWS_EMAIL_IMPACT_REPLAY_VISION')

    if (replayEnabled && !replayVisionEnabled) {
        return null
    }
    if (replayEnabled) {
        return (
            <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
                <h3 className="m-0 text-base font-semibold">What people did after clicking</h3>
                <BindLogic logic={afterClickingScanLogic} props={{ ...impactLogic.props, days, linkTagging }}>
                    <AfterClickingScanPanel />
                </BindLogic>
            </LemonCard>
        )
    }

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
            <h3 className="m-0 text-base font-semibold">What people did after clicking</h3>
            <div className="flex items-start gap-2 border rounded p-3">
                <IconSparkles className="text-lg shrink-0 mt-0.5" />
                <div className="flex flex-col gap-2 items-start">
                    <span className="font-semibold">Session replay is off</span>
                    <span className="text-secondary text-sm">
                        Replay vision will watch the sessions this email starts and group what people did. It needs
                        session replay to record those sessions.
                    </span>
                    <LemonButton
                        type="secondary"
                        size="small"
                        to={urls.settings('project-replay', 'replay')}
                        {...crossSellLinkProps(
                            ProductKey.SESSION_REPLAY,
                            ProductIntentContext.WORKFLOW_EMAIL_IMPACT_TURN_ON_REPLAY
                        )}
                        data-attr="email-impact-turn-on-replay"
                    >
                        Turn on session replay
                    </LemonButton>
                </div>
            </div>
        </LemonCard>
    )
}
