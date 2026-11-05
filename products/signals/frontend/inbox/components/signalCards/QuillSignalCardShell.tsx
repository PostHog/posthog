import { IconChevronDown, IconChevronRight } from '@posthog/icons'
import { Button, Card, CardContent, Text, cn } from '@posthog/quill'

import { TZLabel } from 'lib/components/TZLabel'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { scoutDisplayName } from 'lib/signals/signalCardSourceLine'
import type { SignalNode } from 'scenes/debug/signals/types'
import { urls } from 'scenes/urls'

import { getSourceProductMeta } from '../badges/sourceProductIcons'
import { SignalCardDisclosureState, useSignalCardDisclosure } from './signalCardDisclosure'
import { signalCardSource } from './signalCardParsing'

function QuillSignalCardHeader({
    signal,
    label,
    disclosure,
}: {
    signal: SignalNode
    label?: React.ReactNode
    disclosure: SignalCardDisclosureState | null
}): JSX.Element {
    const meta = getSourceProductMeta(signal.source_product)
    const Icon = meta?.Icon
    const { sourceLine, scoutSkillName } = signalCardSource(signal)

    return (
        <div className="flex min-w-0 items-center gap-2">
            {Icon ? (
                <span className="inline-flex shrink-0 items-center" aria-hidden>
                    <Icon className={cn('text-base', meta.colorClass)} />
                </span>
            ) : (
                <span className="size-2.5 shrink-0 rounded-full bg-border" />
            )}
            <Text size="xs" weight="medium" variant="muted" render={<span />} className="flex min-w-0 items-center">
                <span className="truncate" title={sourceLine}>
                    {/* stopPropagation keeps a scout link click from also triggering an enclosing row link. */}
                    {scoutSkillName ? (
                        <>
                            Scout ·{' '}
                            <LinkPrimitive
                                to={urls.inboxScout(scoutSkillName)}
                                className="text-muted-foreground hover:underline"
                                onClick={(e) => e.stopPropagation()}
                            >
                                {scoutDisplayName(scoutSkillName)}
                            </LinkPrimitive>
                        </>
                    ) : (
                        sourceLine
                    )}
                </span>
                <span className="shrink-0 whitespace-pre">
                    {' · '}
                    <TZLabel time={signal.timestamp} />
                </span>
            </Text>
            {label && (
                <Text size="xs" weight="medium" render={<span />} className="flex-1 truncate">
                    {label}
                </Text>
            )}
            <span className="flex-1" />
            {disclosure ? (
                <Button
                    size="icon"
                    aria-label={disclosure.expanded ? 'Collapse signal details' : 'Expand signal details'}
                    tooltip={disclosure.expanded ? 'Collapse signal details' : 'Expand signal details'}
                    onClick={() => disclosure.onChange(!disclosure.expanded)}
                    className="shrink-0"
                >
                    {disclosure.expanded ? <IconChevronDown /> : <IconChevronRight />}
                </Button>
            ) : null}
        </div>
    )
}

/** Quill sibling of `SignalCardShell`: card container + shared header. Per-source cards render their body as `children`. */
export function QuillSignalCardShell({
    signal,
    label,
    children,
}: {
    signal: SignalNode
    label?: React.ReactNode
    children: React.ReactNode
}): JSX.Element {
    const disclosure = useSignalCardDisclosure()

    return (
        <Card size="sm">
            <CardContent className="flex min-w-0 flex-col gap-2">
                <QuillSignalCardHeader signal={signal} label={label} disclosure={disclosure} />
                {!disclosure || disclosure.expanded ? children : null}
            </CardContent>
        </Card>
    )
}
