import { useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { urls } from 'scenes/urls'

import { ProductIntentContext, ProductKey } from '~/queries/schema/schema-general'

import { crossSellLinkProps } from '../../workflowsCrossSell'
import { emailImpactLogic } from './emailImpactLogic'

export function AfterClickingCard(): JSX.Element {
    const { replayEnabled } = useValues(emailImpactLogic)

    return (
        <LemonCard hoverEffect={false} className="flex flex-col gap-3 p-4">
            <h3 className="m-0 text-base font-semibold">What people did after clicking</h3>
            <div className="flex items-start gap-2 border rounded p-3">
                <IconSparkles className="text-lg shrink-0 mt-0.5" />
                {replayEnabled ? (
                    <div className="flex flex-col gap-1">
                        <span className="font-semibold">See what people do after they click</span>
                        <span className="text-secondary text-sm">
                            Replay vision will watch the sessions this email starts and group what people did. It needs
                            link tagging to find those sessions, so it isn't available for this email yet.
                        </span>
                    </div>
                ) : (
                    <div className="flex flex-col gap-2 items-start">
                        <span className="font-semibold">Session replay is off</span>
                        <span className="text-secondary text-sm">
                            Replay vision will watch the sessions this email starts and group what people did. It needs
                            session replay to record those sessions, and link tagging to find them.
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
                )}
            </div>
        </LemonCard>
    )
}
