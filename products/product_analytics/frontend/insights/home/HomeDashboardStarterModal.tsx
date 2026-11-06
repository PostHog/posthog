import { IconChevronRight, IconCopy, IconDashboard, IconHome, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonModal } from '@posthog/lemon-ui'

export interface HomeDashboardStarterModalProps {
    isOpen: boolean
    onClose: () => void
    onCopyPostHogHome: () => void
    onTalkToAI: () => void
    onChooseExisting: () => void
    hasCustomDashboard: boolean
    onRestorePostHogHome?: () => void
    restoringPostHogHome?: boolean
    creatingWithAI?: boolean
    aiDisabledReason?: string | false
}

export function HomeDashboardStarterModal({
    isOpen,
    onClose,
    onCopyPostHogHome,
    onTalkToAI,
    onChooseExisting,
    hasCustomDashboard,
    onRestorePostHogHome,
    restoringPostHogHome = false,
    creatingWithAI = false,
    aiDisabledReason,
}: HomeDashboardStarterModalProps): JSX.Element {
    const creationDisabledReason = creatingWithAI ? 'Creating your dashboard…' : undefined
    const choices = [
        {
            title: 'Copy and edit the default dashboard',
            description:
                'Copy the charts on this page so you can edit, add, or remove them. You can reset to the PostHog default at any time.',
            icon: <IconCopy />,
            onClick: onCopyPostHogHome,
            dataAttr: 'home-dashboard-copy-posthog-home',
            loading: false,
            disabledReason: creationDisabledReason,
        },
        {
            title: 'Talk to PostHog AI',
            description: 'Describe what you want to track and let PostHog AI build it.',
            icon: <IconSparkles />,
            onClick: onTalkToAI,
            dataAttr: 'home-dashboard-start-ai',
            loading: creatingWithAI,
            disabledReason: creationDisabledReason || aiDisabledReason,
        },
        {
            title: 'Choose an existing dashboard',
            description: 'Show one of this project’s dashboards on this page.',
            icon: <IconDashboard />,
            onClick: onChooseExisting,
            dataAttr: 'home-dashboard-choose-existing',
            loading: false,
            disabledReason: creationDisabledReason,
        },
    ]

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title="Customize this dashboard"
            description="Copy the default dashboard to edit it, or show a different dashboard on this page."
            width="38rem"
            maxWidth="calc(100vw - 2rem)"
            data-attr="home-dashboard-starter-modal"
        >
            <div className="min-w-0 overflow-hidden rounded border border-primary divide-y divide-border">
                {choices.map(({ title, description, icon, onClick, dataAttr, loading, disabledReason }) => (
                    <LemonButton
                        key={dataAttr}
                        type="tertiary"
                        fullWidth
                        icon={icon}
                        sideIcon={<IconChevronRight />}
                        className="!rounded-none"
                        onClick={onClick}
                        loading={loading}
                        disabledReason={disabledReason}
                        data-attr={dataAttr}
                    >
                        <span className="flex min-w-0 flex-col gap-0.5 py-2">
                            <span className="whitespace-normal font-semibold">{title}</span>
                            <span className="whitespace-normal text-xs font-normal text-secondary">{description}</span>
                        </span>
                    </LemonButton>
                ))}
            </div>
            {hasCustomDashboard && onRestorePostHogHome ? (
                <div className="mt-4 border-t border-primary pt-3">
                    <LemonButton
                        type="tertiary"
                        fullWidth
                        icon={<IconHome />}
                        sideIcon={<IconChevronRight />}
                        onClick={onRestorePostHogHome}
                        loading={restoringPostHogHome}
                        disabledReason={creationDisabledReason}
                        data-attr="home-dashboard-restore-posthog-home"
                    >
                        <span className="flex min-w-0 flex-col gap-0.5 py-1">
                            <span className="font-semibold">Reset to PostHog default</span>
                            <span className="whitespace-normal text-xs font-normal text-secondary">
                                Go back to the default product analytics dashboard.
                            </span>
                        </span>
                    </LemonButton>
                </div>
            ) : null}
        </LemonModal>
    )
}
