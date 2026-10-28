import { useActions, useValues } from 'kea'
import { combineUrl } from 'kea-router'

import { IconSparkles, IconX } from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'
import { PostHogCaptureOnViewed } from '@posthog/react'

import { humanFriendlyNumber } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { replayVisionUpsellLogic } from './replayVisionUpsellLogic'

/** The player-card variant of the Replay vision experiment. */
export function ReplayVisionPlayerUpsellCard(): JSX.Element | null {
    const { playerCard, scannerStats, freeCreditsAllowance } = useValues(replayVisionUpsellLogic)
    const { dismiss, reportClicked } = useActions(replayVisionUpsellLogic)

    if (!playerCard) {
        return null
    }

    const isTeamCard = playerCard === 'team'

    return (
        <PostHogCaptureOnViewed
            name="replay_vision_upsell_shown"
            properties={{ placement: 'player', card: playerCard, team_has_scanners: isTeamCard }}
        >
            <LemonCard
                hoverEffect={false}
                className="@container relative p-4"
                data-attr="replay-vision-upsell-player-card"
            >
                <LemonButton
                    className="absolute top-2 right-2"
                    size="xsmall"
                    icon={<IconX />}
                    onClick={() => dismiss('player')}
                    tooltip="Hide this suggestion"
                    aria-label="Dismiss"
                    data-attr="replay-vision-upsell-player-card-dismiss"
                />
                <div className="flex flex-col gap-3 pr-8 @2xl:flex-row @2xl:items-center @2xl:justify-between">
                    <div className="min-w-0 space-y-1">
                        <h3 className="m-0 flex flex-wrap items-center gap-2 text-base font-semibold">
                            <IconSparkles className="text-ai" />
                            <span>
                                {isTeamCard
                                    ? 'Save time: your team already uses Replay vision'
                                    : 'Save time: let Replay vision watch recordings for you'}
                            </span>
                            {isTeamCard && scannerStats && (
                                <LemonTag type="muted">{pluralize(scannerStats.total, 'scanner')}</LemonTag>
                            )}
                        </h3>
                        <p className="m-0 text-sm text-secondary">
                            {isTeamCard
                                ? 'Your teammates have scanners that watch sessions for them. See what they found before you watch the next recording.'
                                : 'You watch more replays than most people on PostHog. Describe what to look for once, and Replay vision finds the sessions where it happens, like rage clicks on checkout or users who get stuck.'}
                        </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-start gap-1 @2xl:items-end">
                        {isTeamCard ? (
                            <LemonButton
                                type="primary"
                                to={urls.replayVision()}
                                onClick={() => reportClicked('player', 'see_team_scanners')}
                                data-attr="replay-vision-upsell-player-card-see-team-scanners"
                            >
                                See your team's scanners
                            </LemonButton>
                        ) : (
                            <LemonButton
                                type="primary"
                                // Pinned: the scanner's `entry_point`, so the scanners this card produces can be counted.
                                to={
                                    combineUrl(urls.replayVisionNewScanner(), { entry_point: 'replay_upsell_player' })
                                        .url
                                }
                                onClick={() => reportClicked('player', 'set_up_scanner')}
                                data-attr="replay-vision-upsell-player-card-set-up-scanner"
                            >
                                Set up a scanner
                            </LemonButton>
                        )}
                        <span className="text-xs text-muted">
                            {isTeamCard
                                ? 'No extra setup.'
                                : freeCreditsAllowance
                                  ? `${humanFriendlyNumber(freeCreditsAllowance)} free credits each month.`
                                  : null}
                        </span>
                    </div>
                </div>
            </LemonCard>
        </PostHogCaptureOnViewed>
    )
}
