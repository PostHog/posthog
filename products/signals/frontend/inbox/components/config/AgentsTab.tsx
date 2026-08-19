import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft, IconCompass } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { scoutFleetLogic } from '../../logics/scoutFleetLogic'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { AgentsRoster } from './AgentsRoster'
import { ConnectionsSection } from './ConnectionsSection'
import { DataSourceSetup } from './DataSourceSetup'
import { SlackNotificationsSection } from './SlackNotificationsSection'

function Subsection({
    title,
    description,
    children,
}: {
    title: string
    description?: string
    children: React.ReactNode
}): JSX.Element {
    return (
        <div className="flex flex-col gap-4 border-t border-primary pt-6 first:border-t-0 first:pt-0">
            <div className="flex flex-col gap-1">
                <h4 className="font-semibold text-sm text-default mb-0">{title}</h4>
                {description && (
                    <p className="text-xs text-secondary mt-0 mb-0 max-w-2xl leading-snug">{description}</p>
                )}
            </div>
            {children}
        </div>
    )
}

/**
 * The roster lives on its own tab now, so this points at it rather than mounting a second copy —
 * two live rosters on one project would each poll the runs window and fight over the same state.
 */
function ScoutsSubsectionLink(): JSX.Element {
    const { scoutConfigs, enabledCount } = useValues(scoutFleetLogic)

    return (
        <div className="flex items-center gap-3 rounded border border-primary bg-surface-primary px-4 py-3">
            <IconCompass className="size-5 shrink-0 text-accent" />
            <span className="flex-1 text-sm text-secondary">
                {scoutConfigs === null
                    ? 'Manage the scouts sweeping this project.'
                    : `${enabledCount} of ${scoutConfigs.length} scouts on patrol.`}
            </span>
            <LemonButton type="secondary" size="small" to={urls.inbox('scouts')}>
                Open scouts
            </LemonButton>
        </div>
    )
}

function BackLink({ onClick }: { onClick: () => void }): JSX.Element {
    return (
        <LemonButton type="tertiary" size="small" icon={<IconArrowLeft />} onClick={onClick} className="-ml-2 w-fit">
            Back
        </LemonButton>
    )
}

/**
 * Full-page Agents tab body for cloud Inbox – a high-fidelity port of the
 * PostHog Desktop Agents view. Composes Connections, the agent roster,
 * Slack, and MCP servers. Session-analysis and data-source setup
 * render inline (replacing the roster) when their sub-flow is open.
 */
export function AgentsTab(): JSX.Element {
    const { dataSourceSetupSource } = useValues(signalSourcesLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { loadSources, loadSourceConfigs, loadToolDataEvents, closeDataSourceSetup, onDataSourceSetupComplete } =
        useActions(signalSourcesLogic)

    useEffect(() => {
        loadSources()
        loadSourceConfigs()
        loadToolDataEvents()
    }, []) // eslint-disable-line react-hooks/exhaustive-deps

    let agentsBody: JSX.Element
    if (dataSourceSetupSource !== null) {
        agentsBody = (
            <div className="flex flex-col gap-3">
                <BackLink onClick={closeDataSourceSetup} />
                <DataSourceSetup source={dataSourceSetupSource} onComplete={() => onDataSourceSetupComplete()} />
            </div>
        )
    } else {
        agentsBody = <AgentsRoster />
    }

    return (
        <div className="flex flex-col">
            <div className="mx-auto max-w-4xl w-full px-6 py-6 flex flex-col gap-8">
                <Subsection
                    title="Connections"
                    description="Foundational integrations signal sources read from and write to."
                >
                    <ConnectionsSection />
                </Subsection>

                <Subsection
                    title="Scouts"
                    description="Scheduled agents that sweep this project on a cadence and emit signals to your inbox."
                >
                    <ScoutsSubsectionLink />
                </Subsection>

                <Subsection
                    title="Signal sources"
                    description="Each source watches for signals, and spins up an agent to look into them."
                >
                    {agentsBody}
                </Subsection>

                {featureFlags[FEATURE_FLAGS.INBOX_SLACK_NOTIFICATIONS] && (
                    <Subsection
                        title="Slack"
                        description="Post reports to channels and ping suggested reviewers. Invite PostHog with /invite @PostHog in each channel you use."
                    >
                        <SlackNotificationsSection />
                    </Subsection>
                )}
            </div>
        </div>
    )
}

export default AgentsTab
