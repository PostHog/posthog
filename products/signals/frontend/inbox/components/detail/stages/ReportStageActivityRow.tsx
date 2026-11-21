import { useState } from 'react'

import { IconChevronRight, IconCompass } from '@posthog/icons'
import { Avatar, AvatarFallback, Badge, Button, Text, cn } from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { ReportActivityActor, ReportActivityEntry } from './reportActivityEntries'
import { ReportStageProse } from './ReportStageProse'

function ActorAvatar({ actor }: { actor: ReportActivityActor }): JSX.Element {
    if (actor.kind === 'scout') {
        return (
            <Avatar size="xs">
                <AvatarFallback>
                    <IconCompass />
                </AvatarFallback>
            </Avatar>
        )
    }
    return (
        <QuillPersonAvatar
            name={actor.name}
            email={actor.kind === 'person' ? actor.email : undefined}
            size="xs"
            system={actor.kind === 'posthog'}
        />
    )
}

export function ReportStageActivityRow({
    entry,
    defaultOpen = false,
}: {
    entry: ReportActivityEntry
    defaultOpen?: boolean
}): JSX.Element {
    const [open, setOpen] = useState(defaultOpen)
    const bodyId = `inbox-report-activity-${entry.id}`

    return (
        <li className="flex flex-col gap-2 py-1.5">
            <div className="flex items-start gap-2">
                <span className="pt-px">
                    <ActorAvatar actor={entry.actor} />
                </span>
                <Text size="sm" render={<div />} className="flex min-w-0 flex-1 flex-wrap items-center gap-x-1.5">
                    <span className="font-medium">{entry.actor.name}</span>
                    <span className="text-muted-foreground">{entry.action}</span>
                    {entry.badge && <Badge variant={entry.badge.variant}>{entry.badge.label}</Badge>}
                    {entry.reference &&
                        (entry.reference.url ? (
                            <Button
                                variant="link-foreground"
                                size="inline"
                                className={cn(entry.reference.mono && 'font-mono text-xs')}
                                render={<LinkPrimitive to={entry.reference.url} target="_blank" />}
                            >
                                {entry.reference.text}
                            </Button>
                        ) : (
                            <span className={cn('min-w-0 truncate', entry.reference.mono && 'font-mono text-xs')}>
                                {entry.reference.text}
                            </span>
                        ))}
                </Text>
                <Text size="xs" variant="muted" render={<span />} className="shrink-0 whitespace-nowrap pt-0.5">
                    <TZLabel time={entry.at} />
                </Text>
                {entry.body ? (
                    <Button
                        size="icon-xs"
                        variant="link-muted"
                        aria-label={open ? 'Hide the note' : 'Show the note'}
                        aria-expanded={open}
                        aria-controls={bodyId}
                        onClick={() => setOpen(!open)}
                        data-attr="inbox-report-activity-toggle"
                    >
                        <IconChevronRight className={cn('transition-transform duration-200', open && 'rotate-90')} />
                    </Button>
                ) : (
                    <span className="w-5 shrink-0" aria-hidden />
                )}
            </div>
            {open && entry.body && (
                <div id={bodyId} className="ms-7 rounded-md border border-border bg-card px-3 py-2.5">
                    <ReportStageProse markdown={entry.body} size="xs" />
                </div>
            )}
        </li>
    )
}
