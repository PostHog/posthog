import { router } from 'kea-router'

import { IconCheck, IconNotification, IconPencil, IconPlay, IconTrash } from '@posthog/icons'
import { LemonButton, LemonCard } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { IncidentTimeline } from './IncidentTimeline'
import { Incident } from './uptimeSceneLogic'

interface IncidentTileProps {
    incident: Incident
    monitorName?: string
    linkToMonitor?: boolean
    onEdit: () => void
    onResolve: () => void
    onReopen: () => void
    onDelete: () => void
    onPostUpdate: () => void
}

export function IncidentTile({
    incident,
    monitorName,
    linkToMonitor = false,
    onEdit,
    onResolve,
    onReopen,
    onDelete,
    onPostUpdate,
}: IncidentTileProps): JSX.Element {
    const ongoing = incident.resolved_at === null
    const stop = (e: React.MouseEvent): void => e.stopPropagation()

    return (
        <LemonCard
            hoverEffect={linkToMonitor}
            onClick={linkToMonitor ? () => router.actions.push(urls.uptimeMonitor(incident.monitor_id)) : undefined}
            className="group flex flex-col gap-3 p-4 h-full"
        >
            <div className="flex items-start justify-between gap-2 min-w-0">
                <div className="flex items-center gap-2 min-w-0">
                    <span
                        className={cn(
                            'inline-block w-2.5 h-2.5 rounded-full shrink-0',
                            ongoing ? 'bg-danger animate-pulse' : 'bg-success'
                        )}
                        aria-hidden
                    />
                    <div className="font-semibold truncate" title={incident.name}>
                        {incident.name}
                    </div>
                </div>
                <div
                    className="flex items-center gap-1 shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                    onClick={stop}
                >
                    <LemonButton
                        size="xsmall"
                        icon={<IconNotification />}
                        onClick={onPostUpdate}
                        tooltip="Post timeline update"
                    />
                    <LemonButton size="xsmall" icon={<IconPencil />} onClick={onEdit} tooltip="Edit" />
                    {ongoing ? (
                        <LemonButton
                            size="xsmall"
                            icon={<IconCheck />}
                            onClick={onResolve}
                            tooltip="Mark as resolved"
                        />
                    ) : (
                        <LemonButton size="xsmall" icon={<IconPlay />} onClick={onReopen} tooltip="Reopen" />
                    )}
                    <LemonButton
                        size="xsmall"
                        icon={<IconTrash />}
                        status="danger"
                        onClick={onDelete}
                        tooltip="Delete"
                    />
                </div>
            </div>

            {incident.description && (
                <div className="text-xs text-secondary whitespace-pre-wrap line-clamp-3">{incident.description}</div>
            )}

            {incident.updates && incident.updates.length > 0 && (
                <div onClick={stop}>
                    <IncidentTimeline updates={incident.updates} limit={3} />
                </div>
            )}

            {!ongoing && incident.resolution_note && (
                <div className="text-xs whitespace-pre-wrap line-clamp-3 p-2 rounded bg-surface-secondary text-primary">
                    <span className="font-semibold">Resolution: </span>
                    {incident.resolution_note}
                </div>
            )}

            <div className="mt-auto flex flex-col gap-0.5 text-[11px] text-secondary">
                {monitorName && (
                    <span className="font-medium text-primary truncate" title={monitorName}>
                        {monitorName}
                    </span>
                )}
                <span>Started {dayjs(incident.started_at).fromNow()}</span>
                {incident.resolved_at && <span>Resolved {dayjs(incident.resolved_at).fromNow()}</span>}
            </div>
        </LemonCard>
    )
}
