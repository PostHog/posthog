import { IconTelescope } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonTag } from 'lib/lemon-ui/LemonTag'

export interface DashboardScoutOfferProps {
    onSetUp: () => void
    disabledReason?: string | null
}

export function DashboardScoutOffer({ onSetUp, disabledReason }: DashboardScoutOfferProps): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="p-3">
            <div className="flex flex-col gap-3 @min-[30rem]/subscription-modal:flex-row @min-[30rem]/subscription-modal:items-center">
                <div className="flex items-center justify-center rounded bg-fill-secondary size-9 text-lg shrink-0">
                    <IconTelescope />
                </div>
                <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 text-sm font-medium">
                        <span>Watch this dashboard with a scout</span>
                        <LemonTag type="highlight" size="small">
                            New
                        </LemonTag>
                    </div>
                    <div className="text-xs text-secondary">
                        Get a Slack message when something changes here, with the likely cause. A scout learns what is
                        normal, follows your notes, and can use your other data and code.
                    </div>
                </div>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={onSetUp}
                    disabledReason={disabledReason}
                    className="self-start shrink-0 @min-[30rem]/subscription-modal:self-center"
                    data-attr="dashboard-scout-set-up"
                >
                    Set up a scout
                </LemonButton>
            </div>
        </LemonCard>
    )
}
