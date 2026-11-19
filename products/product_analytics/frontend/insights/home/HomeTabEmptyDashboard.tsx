import { IconHome, IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

export interface HomeTabEmptyDashboardProps {
    onContinueWithAI: () => void
    onResetToDefault: () => void
    aiDisabledReason?: string | false
    resetting?: boolean
}

export function HomeTabEmptyDashboard({
    onContinueWithAI,
    onResetToDefault,
    aiDisabledReason,
    resetting = false,
}: HomeTabEmptyDashboardProps): JSX.Element {
    return (
        <div
            className="flex flex-col items-center gap-3 rounded border border-primary px-4 py-10 text-center"
            data-attr="home-tab-empty-dashboard"
        >
            <h3 className="mb-0 text-base font-semibold">This dashboard has no charts yet</h3>
            <p className="mb-0 max-w-120 text-secondary">
                Continue with PostHog AI to add charts, or reset to the PostHog default dashboard.
            </p>
            <div className="flex flex-wrap justify-center gap-2">
                <LemonButton
                    type="primary"
                    icon={<IconSparkles />}
                    onClick={onContinueWithAI}
                    disabledReason={aiDisabledReason || undefined}
                    data-attr="home-tab-empty-dashboard-continue-ai"
                >
                    Continue with PostHog AI
                </LemonButton>
                <LemonButton
                    type="secondary"
                    icon={<IconHome />}
                    onClick={onResetToDefault}
                    loading={resetting}
                    data-attr="home-tab-empty-dashboard-reset"
                >
                    Reset to PostHog default
                </LemonButton>
            </div>
        </div>
    )
}
