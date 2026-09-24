import { LemonButton, LemonCard } from '@posthog/lemon-ui'

export function SelfDrivingOptInCard({
    onTurnOn,
    turningOn,
}: {
    onTurnOn: () => void
    turningOn: boolean
}): JSX.Element {
    return (
        <LemonCard className="flex max-w-3xl flex-col gap-3" hoverEffect={false}>
            <h3 className="mb-0">Self-driving for workflows</h3>
            <p className="mb-0">
                PostHog's own scout reads your active email workflows once a day. When several workflows reach mostly
                the same people within a few days, it files a suggestion here: move a send, or exclude one audience from
                another.
            </p>
            <p className="mb-0">It changes nothing on its own. You decide what to apply.</p>
            <div>
                <LemonButton
                    type="primary"
                    onClick={onTurnOn}
                    loading={turningOn}
                    disabledReason={turningOn ? 'Turning on Self-driving' : undefined}
                    data-attr="workflows-self-driving-turn-on"
                >
                    Turn on Self-driving
                </LemonButton>
            </div>
        </LemonCard>
    )
}
