import { useActions, useMountedLogic, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconBolt, IconCheckCircle, IconChevronRight, IconCompass, IconGithub } from '@posthog/icons'
import { LemonModal, LemonSkeleton, LemonTag, Link } from '@posthog/lemon-ui'

import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { slackChannelDisplayName } from 'lib/integrations/slackChannel'
import { IconSlack } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'
import { GithubIntegration } from 'scenes/integrations/components/GithubIntegration'
import { urls } from 'scenes/urls'

import { inboxUsageLogic } from '../../logics/inboxUsageLogic'
import { scoutFleetLogic } from '../../logics/scoutFleetLogic'
import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'
import { userAutonomyLogic } from '../../logics/userAutonomyLogic'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { SelfDrivingSection } from '../config/SelfDrivingSection'
import { SignalSourcesPanel } from '../config/SignalSourcesPanel'
import { SlackNotificationsSection } from '../config/SlackNotificationsSection'
import { AgentSetupModalKey, agentSetupModalLogic } from './agentSetupModalLogic'
import { InboxUsageWidget } from './InboxUsageWidget'
import { InstallationSetupSection } from './InstallationSetupSection'
import { SetupSection } from './SetupSection'

type WidgetTone = 'todo' | 'done' | 'neutral'
/** Visual weight reflecting how important / frequently edited a part of the setup is. */
type WidgetSize = 'lg' | 'md' | 'sm'

interface SetupWidgetCardProps {
    icon: JSX.Element
    title: string
    /** Short status line; falls back to a skeleton while `loading`. */
    status: React.ReactNode
    tone: WidgetTone
    size: WidgetSize
    loading?: boolean
    /** One-line context, shown on `lg` cards only. */
    description?: string
    onClick?: () => void
    to?: string
    /** Extra content under the status (e.g. MCP brand icons). */
    children?: React.ReactNode
}

function TrailingAffordance({
    tone,
    to,
    loading,
}: {
    tone: WidgetTone
    to?: string
    loading?: boolean
}): JSX.Element | null {
    if (loading) {
        return <LemonSkeleton className="h-4 w-12 rounded" />
    }
    if (tone === 'todo') {
        return (
            <LemonTag type="warning" size="small">
                Set up
            </LemonTag>
        )
    }
    if (tone === 'done') {
        return <IconCheckCircle className="size-4 shrink-0 text-success" />
    }
    if (to) {
        return <IconChevronRight className="size-4 shrink-0 text-muted transition-colors group-hover:text-default" />
    }
    return null
}

const ICON_BOX_CLASS: Record<WidgetSize, string> = {
    sm: 'size-5 [&_svg]:size-3',
    md: 'size-6 [&_svg]:size-3.5',
    lg: 'size-7 [&_svg]:size-4',
}
const TITLE_CLASS: Record<WidgetSize, string> = {
    sm: 'text-[13px] font-medium',
    md: 'text-[13px] font-medium',
    lg: 'text-[13px] font-semibold',
}
const CARD_PADDING_CLASS: Record<WidgetSize, string> = {
    sm: 'px-2.5 py-1.5',
    md: 'px-2.5 py-2',
    lg: 'px-2.5 py-2 gap-0.5',
}

function SetupWidgetCard(props: SetupWidgetCardProps): JSX.Element {
    const { icon, title, status, tone, size, loading, description, onClick, to, children } = props

    const cardClassName = cn(
        'group flex rounded border border-primary bg-surface-primary text-left no-underline cursor-pointer transition-colors hover:border-secondary',
        size === 'sm' ? 'items-center justify-between gap-2' : 'flex-col',
        CARD_PADDING_CLASS[size]
    )

    // Compact single-row layout for the lowest-importance widgets.
    const content =
        size === 'sm' ? (
            <>
                <div className="flex items-center gap-2 min-w-0">
                    <span
                        className={cn(
                            'flex shrink-0 items-center justify-center rounded bg-surface-secondary text-default',
                            ICON_BOX_CLASS[size]
                        )}
                    >
                        {icon}
                    </span>
                    <span className={cn('text-default truncate', TITLE_CLASS[size])}>{title}</span>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                    {loading ? (
                        <LemonSkeleton className="h-3 w-16" />
                    ) : (
                        <span className="text-xs text-secondary">{status}</span>
                    )}
                    <TrailingAffordance tone={tone} to={to} loading={loading} />
                </div>
            </>
        ) : (
            <div className="flex items-start gap-2 min-w-0">
                <span
                    className={cn(
                        'flex shrink-0 items-center justify-center rounded bg-surface-secondary text-default',
                        ICON_BOX_CLASS[size]
                    )}
                >
                    {icon}
                </span>
                <div className="flex flex-col gap-0.5 min-w-0 flex-1">
                    <div className="flex items-center justify-between gap-1.5">
                        <span className={cn('text-default truncate', TITLE_CLASS[size])}>{title}</span>
                        <TrailingAffordance tone={tone} to={to} loading={loading} />
                    </div>
                    {loading ? (
                        <LemonSkeleton className="h-3 w-20" />
                    ) : (
                        <span className="text-xs text-secondary truncate">{status}</span>
                    )}
                    {size === 'lg' && description && (
                        <p className="text-xs text-tertiary leading-snug mb-0">{description}</p>
                    )}
                    {children}
                </div>
            </div>
        )

    if (to) {
        return (
            <Link to={to} className={cardClassName}>
                {content}
            </Link>
        )
    }
    return (
        <button type="button" onClick={onClick} className={cardClassName}>
            {content}
        </button>
    )
}

function SignalSourcesWidget(): JSX.Element {
    const { sourceConfigs, enabledSourcesCount } = useValues(signalSourcesLogic)
    const { openSetupModal } = useActions(agentSetupModalLogic)
    const hasAny = enabledSourcesCount > 0
    return (
        <SetupWidgetCard
            icon={<IconBolt />}
            title="Signal sources"
            size="lg"
            tone={hasAny ? 'done' : 'todo'}
            loading={sourceConfigs === null}
            status={hasAny ? `${enabledSourcesCount} watching` : 'None active yet'}
            description="Each source watches for signals, and spins up an agent to look into them."
            onClick={() => openSetupModal('signal-sources')}
        />
    )
}

function ScoutTroopWidget(): JSX.Element {
    useMountedLogic(scoutFleetLogic)
    const { scoutConfigs, enabledCount } = useValues(scoutFleetLogic)
    const hasAny = enabledCount > 0
    return (
        <SetupWidgetCard
            icon={<IconCompass />}
            title="Scout troop"
            size="lg"
            tone={hasAny ? 'done' : 'todo'}
            loading={scoutConfigs === null}
            status={hasAny ? `${enabledCount} on patrol` : 'No scouts running'}
            description="Scheduled agents that sweep this project on a cadence and report signals."
            to={urls.inbox('scouts')}
        />
    )
}

function CodeAccessWidget(): JSX.Element {
    const { getIntegrationsByKind, integrationsLoading } = useValues(integrationsLogic)
    const { openSetupModal } = useActions(agentSetupModalLogic)
    const hasGithub = getIntegrationsByKind(['github']).length > 0
    return (
        <SetupWidgetCard
            icon={<IconGithub />}
            title="Code access"
            size="md"
            tone={hasGithub ? 'done' : 'todo'}
            loading={integrationsLoading && !hasGithub}
            status={hasGithub ? 'GitHub connected' : 'Foundational. Connect to start.'}
            onClick={() => openSetupModal('github')}
        />
    )
}

function NotificationsWidget(): JSX.Element {
    useMountedLogic(userAutonomyLogic)
    const { slackIntegrations, integrationsLoading } = useValues(integrationsLogic)
    const { autonomyConfig } = useValues(userAutonomyLogic)
    const { teamConfig } = useValues(signalTeamConfigLogic)
    const { openSetupModal } = useActions(agentSetupModalLogic)

    // Either target counts as set up: the team-wide channel catches every actionable report,
    // the personal channel pings the suggested reviewer. The status names each configured one.
    const teamChannel = teamConfig?.default_slack_notification_channel ?? null
    const userChannel = autonomyConfig?.slack_notification_channel ?? null
    const channelLabels = [
        teamChannel ? `Team ${slackChannelDisplayName(teamChannel)}` : null,
        userChannel ? `You ${slackChannelDisplayName(userChannel)}` : null,
    ].filter(Boolean)
    const notifying = (slackIntegrations?.length ?? 0) > 0 && channelLabels.length > 0
    return (
        <SetupWidgetCard
            icon={<IconSlack className="grayscale" />}
            title="Notifications"
            size="md"
            tone={notifying ? 'done' : 'todo'}
            loading={integrationsLoading && slackIntegrations === undefined}
            status={notifying ? channelLabels.join(' · ') : 'Not connected'}
            onClick={() => openSetupModal('slack')}
        />
    )
}

/**
 * The GitHub OAuth round trip returns to `next`, and this modal opens from the rail beside any of the
 * list tabs – so `next` has to be wherever the user actually started, not a fixed tab. `setup=github`
 * comes back with them so the modal reopens showing the result.
 */
function GithubSetupBody(): JSX.Element {
    const { location, searchParams } = useValues(router)
    return (
        <GithubIntegration
            next={combineUrl(location.pathname, { ...searchParams, setup: 'github' }).url}
            connectSurface="signals_agent_setup"
        />
    )
}

const SETUP_MODALS: Record<
    AgentSetupModalKey,
    { title: string; description: string; width: number; body: JSX.Element }
> = {
    'signal-sources': {
        title: 'Signal sources',
        description: 'Each source watches for signals, and spins up an agent to look into them.',
        width: 760,
        body: <SignalSourcesPanel />,
    },
    slack: {
        title: 'Notifications',
        description: 'Get pinged in Slack when you’re a suggested reviewer on a new report.',
        width: 560,
        body: <SlackNotificationsSection />,
    },
    github: {
        title: 'GitHub',
        description: 'Connect GitHub so agents can read repositories and open pull requests.',
        width: 760,
        body: <GithubSetupBody />,
    },
}

function SetupModal(): JSX.Element {
    const { openModal } = useValues(agentSetupModalLogic)
    const { closeSetupModal } = useActions(agentSetupModalLogic)
    const config = openModal ? SETUP_MODALS[openModal] : null
    return (
        <LemonModal
            isOpen={config !== null}
            onClose={closeSetupModal}
            title={config?.title ?? ''}
            description={config?.description}
            width={config?.width}
        >
            {config?.body}
        </LemonModal>
    )
}

/**
 * The agent-setup widgets, grouped into Agents / Connections. Each widget shows
 * status and nudges the user to finish that part of the setup. Signal sources and Scout troop
 * (most edited) are largest; connections medium and open management modals.
 *
 * Rendered two ways: `rail` (a column to the right of the tabs on wide viewports) and
 * `stacked` (the Configuration tab body on narrow viewports).
 */
export function AgentSetupColumn({ layout }: { layout: 'rail' | 'stacked' }): JSX.Element {
    useMountedLogic(integrationsLogic)
    useMountedLogic(signalSourcesLogic)
    // The usage widget renders nothing without the billing product, so the section title
    // must hide with it rather than sit over an empty area.
    const { product: inboxUsageProduct, isLoading: inboxUsageLoading } = useValues(inboxUsageLogic)

    return (
        <div
            className={cn(
                'flex flex-col gap-5',
                layout === 'stacked' ? 'mx-auto w-full max-w-2xl px-6 py-6' : 'px-4 py-3'
            )}
        >
            <InstallationSetupSection />
            <SetupSection title="Agents">
                <SignalSourcesWidget />
                <ScoutTroopWidget />
                <SelfDrivingSection />
            </SetupSection>
            <SetupSection title="Connections">
                <CodeAccessWidget />
                <NotificationsWidget />
            </SetupSection>
            {(inboxUsageProduct != null || inboxUsageLoading) && (
                <SetupSection title="Usage">
                    <InboxUsageWidget />
                </SetupSection>
            )}
            <SetupModal />
        </div>
    )
}
