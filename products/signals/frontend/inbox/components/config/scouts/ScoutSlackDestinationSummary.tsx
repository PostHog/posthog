import { LemonTag } from '@posthog/lemon-ui'

import { slackChannelDisplayName } from 'lib/integrations/slackChannel'

import type { IntegrationType } from '~/types'

import type { SignalScoutSlackDestinationApi } from 'products/signals/frontend/generated/api.schemas'

/** Why the next run cannot deliver to the saved target, or `null` when nothing is wrong. */
type DestinationFault = 'disconnected' | 'reconnect' | null

/**
 * A picker value carries the channel name after a pipe. A destination saved through the API can
 * hold a bare channel id instead, which names nothing a reader recognizes, so it falls back to the
 * same generic label the picker uses for a channel it cannot name.
 */
function channelLabel(channel: string): string {
    const name = slackChannelDisplayName(channel)
    return name === channel ? 'Slack channel' : name
}

/**
 * Whether the workspace behind a saved destination can still deliver. Both faults come from the
 * integration list, which loads while the section is closed, so neither costs a request. The
 * picker's own health checks only run once the section opens, and a report that never arrives is
 * exactly what a reader must not have to open the section to find out about.
 */
function destinationFault(
    destination: SignalScoutSlackDestinationApi | null | undefined,
    workspaces: IntegrationType[],
    loading: boolean
): DestinationFault {
    if (loading) {
        return null
    }
    const workspace = workspaces.find((candidate) => candidate.id === destination?.integration_id)
    if (!workspace) {
        return 'disconnected'
    }
    // The API records a refresh failure here, which is how a revoked or expired token surfaces
    // without asking Slack again.
    return workspace.errors ? 'reconnect' : null
}

/**
 * Where this scout's output goes, for the collapsed header of the settings form. The saved
 * destination answers on its own, so a scout with Slack set up reads the same before the workspace
 * list arrives.
 */
export function ScoutSlackDestinationSummary({
    destination,
    workspaces,
    loading,
}: {
    destination?: SignalScoutSlackDestinationApi | null
    /** Slack workspaces connected to the project. Empty until `loading` is false. */
    workspaces: IntegrationType[]
    loading: boolean
}): JSX.Element | null {
    const channel = destination?.channel
    const recipientCount = destination?.users?.length ?? 0

    if (!channel && recipientCount === 0) {
        // A project with Slack connected must not read "Not connected" while its workspaces load,
        // so the header stays blank until the list resolves.
        if (loading) {
            return null
        }
        return <span className="text-[11.5px] text-muted">{workspaces.length > 0 ? 'Off' : 'Not connected'}</span>
    }

    const fault = destinationFault(destination, workspaces, loading)

    return (
        <>
            {channel ? (
                <LemonTag size="small" type="option">
                    {channelLabel(channel)}
                </LemonTag>
            ) : (
                <span className="text-[11.5px] text-muted">
                    DM to {recipientCount} {recipientCount === 1 ? 'person' : 'people'}
                </span>
            )}
            {/* The scout harness reads `thread_reports` once and applies it to a channel and to
                each direct message alike, so both targets report it. */}
            {destination?.thread_reports ? (
                <LemonTag size="small" type="muted">
                    Threaded
                </LemonTag>
            ) : null}
            {fault === 'disconnected' ? (
                <LemonTag size="small" type="warning">
                    Disconnected
                </LemonTag>
            ) : null}
            {fault === 'reconnect' ? (
                <LemonTag size="small" type="danger">
                    Reconnect
                </LemonTag>
            ) : null}
        </>
    )
}
