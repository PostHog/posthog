import type { ReactNode } from 'react'

import * as moneyPng from '@posthog/brand/hoggies/png/money'
import { IconCheckCircle, IconInfo } from '@posthog/icons'
import {
    Accordion,
    AccordionContent,
    AccordionItem,
    AccordionTrigger,
    Badge,
    Button,
    Card,
    CardContent,
    CardFooter,
    Collapsible,
    CollapsibleContent,
    CollapsibleTrigger,
    Heading,
    Spinner,
    Text,
} from '@posthog/quill'

import { pngHoggie } from 'lib/brand/hoggies'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

const HedgehogMoney = pngHoggie(moneyPng)

const STATUS_BADGE = {
    'Sync failed': 'destructive',
    'Needs attention': 'warning',
    Connected: 'info',
    Syncing: 'info',
} as const

export interface QuillSourceSetupConnection {
    id: string
    name: string
    status: keyof typeof STATUS_BADGE
    detail: string
    action?: ReactNode
    manageUrl: string | null
}

export function QuillSourceSetupPanel({
    title,
    description,
    busy,
    compact,
    showScanBadge,
    showIllustration,
    showEmptyHint,
    showIntro,
    showOrganicKeywordsIntro,
    showFirstSyncNote,
    showBackgroundImportNote,
    headerAction,
    footer,
    groups,
    expandedGroups,
    onExpandedGroupsChange,
    manageSourceDataAttr,
    suggestions,
    onDismiss,
    onRestore,
    rescanLabel,
    onRescan,
    rescanLoading,
    rescanDisabledReason,
}: {
    title: string
    description: string
    busy: boolean
    compact: boolean
    showScanBadge: boolean
    showIllustration: boolean
    showEmptyHint: boolean
    showIntro: boolean
    showOrganicKeywordsIntro: boolean
    showFirstSyncNote: boolean
    showBackgroundImportNote: boolean
    headerAction?: ReactNode
    footer?: ReactNode
    groups: { sourceType: string; label: string; connections: QuillSourceSetupConnection[] }[]
    expandedGroups: string[]
    onExpandedGroupsChange: (expanded: string[]) => void
    manageSourceDataAttr: string
    suggestions: {
        id: string
        sourceType: string
        name: string
        found: string
        evidence: string
        connectUrl: string | null
    }[]
    onDismiss?: (id: string) => void
    onRestore?: () => void
    rescanLabel: string
    onRescan?: () => void
    rescanLoading: boolean
    rescanDisabledReason?: string | null
}): JSX.Element {
    const rescanButton = onRescan ? (
        <Button
            variant="outline"
            onClick={onRescan}
            loading={rescanLoading}
            disabledReason={rescanDisabledReason}
            data-attr="marketing-onboarding-rescan"
        >
            {rescanLabel}
        </Button>
    ) : null

    return (
        <Card size={compact ? 'sm' : 'default'} className="w-full">
            <CardContent className={compact ? 'flex flex-col gap-3' : 'flex flex-col gap-5'}>
                {showScanBadge && (
                    <div>
                        <Badge>7-day event scan</Badge>
                    </div>
                )}
                <div className="flex items-start gap-4" role={busy ? 'status' : undefined}>
                    {busy ? <Spinner className="mt-1 shrink-0" /> : null}
                    <div className="flex min-w-0 flex-1 flex-col gap-1">
                        <Heading size="base" render={<h3 className="m-0" />}>
                            {title}
                        </Heading>
                        <Text size="xs" variant="muted" render={<p className="m-0 max-w-xl" />}>
                            {description}
                        </Text>
                    </div>
                    {!busy && showIllustration && (
                        <HedgehogMoney className={compact ? 'w-12 shrink-0' : 'w-20 shrink-0'} />
                    )}
                    {headerAction}
                </div>
                {showEmptyHint && (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        Make sure your ad links include UTM parameters, such as utm_source and utm_medium, and that
                        PostHog captures them.
                    </Text>
                )}
                {showIntro && (
                    <div className="flex flex-col gap-1">
                        <Text size="xs" weight="semibold" render={<span className="m-0" />}>
                            Your marketing data in one place
                        </Text>
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            Compare campaign performance across your marketing sources. Use PostHog events as conversion
                            goals to measure conversion costs and ROAS.
                        </Text>
                        {showOrganicKeywordsIntro && (
                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                Compare paid keywords and organic search queries to optimize your search ads.
                            </Text>
                        )}
                    </div>
                )}
                {groups.length > 0 && (
                    <Accordion
                        multiple
                        value={expandedGroups}
                        onValueChange={(expanded) => onExpandedGroupsChange(expanded as string[])}
                    >
                        {groups.map((group) => (
                            <AccordionItem key={group.sourceType} value={group.sourceType}>
                                <AccordionTrigger>
                                    <span className="flex min-w-0 flex-wrap items-center gap-2">
                                        <SourceIcon type={group.sourceType} size="small" disableTooltip />
                                        <strong>{group.label}</strong>
                                        <span className="text-muted-foreground">{`${group.connections.length} ${group.connections.length === 1 ? 'connection' : 'connections'}`}</span>
                                    </span>
                                </AccordionTrigger>
                                <AccordionContent className="flex flex-col divide-y divide-border">
                                    {group.connections.map((connection) => (
                                        <div
                                            key={connection.id}
                                            className="flex flex-wrap items-start justify-between gap-3 py-3"
                                        >
                                            <div className="flex min-w-0 flex-1 basis-64 flex-col gap-2 break-words">
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <Text
                                                        size="xs"
                                                        weight="semibold"
                                                        render={<span className="m-0 break-all" />}
                                                    >
                                                        {connection.name}
                                                    </Text>
                                                    <Badge variant={STATUS_BADGE[connection.status]}>
                                                        {connection.status}
                                                    </Badge>
                                                </div>
                                                <Text
                                                    size="xs"
                                                    variant="muted"
                                                    render={<p className="m-0 whitespace-pre-line" />}
                                                >
                                                    {connection.detail}
                                                </Text>
                                            </div>
                                            {connection.action ? (
                                                <div className="ml-auto shrink-0">{connection.action}</div>
                                            ) : connection.manageUrl ? (
                                                <div className="ml-auto shrink-0">
                                                    <Button
                                                        variant="outline"
                                                        nativeButton={false}
                                                        render={<LinkPrimitive to={connection.manageUrl} />}
                                                        data-attr={manageSourceDataAttr}
                                                        // Accordion panels underline every link inside them.
                                                        className="no-underline!"
                                                    >
                                                        Manage source
                                                    </Button>
                                                </div>
                                            ) : null}
                                        </div>
                                    ))}
                                </AccordionContent>
                            </AccordionItem>
                        ))}
                    </Accordion>
                )}
                {suggestions.length > 0 && !busy && (
                    <div className="flex flex-col divide-y divide-border border-t border-border">
                        {suggestions.map((suggestion) => (
                            <div
                                key={suggestion.id}
                                className={compact ? 'flex flex-col gap-2 py-2' : 'flex flex-col gap-2 py-4'}
                            >
                                <div className="flex flex-wrap items-center justify-between gap-3">
                                    <div className="flex min-w-0 items-center gap-3">
                                        <SourceIcon type={suggestion.sourceType} size="small" disableTooltip />
                                        <div className="flex min-w-0 flex-col">
                                            <Text size="xs" weight="semibold" render={<span className="m-0" />}>
                                                {suggestion.name}
                                            </Text>
                                            <Text size="xs" variant="muted" render={<span className="m-0" />}>
                                                {suggestion.found}
                                            </Text>
                                        </div>
                                    </div>
                                    <div className="flex flex-wrap items-center gap-2">
                                        {suggestion.connectUrl && (
                                            <Button
                                                variant="outline"
                                                nativeButton={false}
                                                render={<LinkPrimitive to={suggestion.connectUrl} />}
                                                data-attr="marketing-onboarding-connect-source"
                                            >
                                                Connect
                                            </Button>
                                        )}
                                        {onDismiss && (
                                            <Button variant="outline" onClick={() => onDismiss(suggestion.id)}>
                                                Dismiss
                                            </Button>
                                        )}
                                    </div>
                                </div>
                                {!compact && (
                                    <Collapsible>
                                        <CollapsibleTrigger>View detection details</CollapsibleTrigger>
                                        <CollapsibleContent>
                                            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                                                {suggestion.evidence}
                                            </Text>
                                        </CollapsibleContent>
                                    </Collapsible>
                                )}
                            </div>
                        ))}
                    </div>
                )}
                {onRestore && (
                    <div>
                        <Button variant="outline" onClick={onRestore}>
                            Restore suggestions
                        </Button>
                    </div>
                )}
                {!compact && rescanButton && <div>{rescanButton}</div>}
                {!busy && rescanDisabledReason && (
                    <Text size="xs" variant="muted" render={<p className="m-0" />}>
                        {rescanDisabledReason}
                    </Text>
                )}
                {showFirstSyncNote && (
                    <div className="flex items-start gap-2 text-xs text-muted-foreground">
                        <IconInfo className="mt-0.5 shrink-0" />
                        <span>Spend data appears after the first sync finishes.</span>
                    </div>
                )}
                {showBackgroundImportNote && (
                    <div className="flex items-start gap-2 text-xs text-muted-foreground">
                        <IconCheckCircle className="mt-0.5 shrink-0" />
                        <span>You can leave this page. Your import will continue in the background.</span>
                    </div>
                )}
            </CardContent>
            {(footer || (compact && rescanButton)) && (
                <CardFooter className="flex-wrap justify-between gap-3">
                    {footer}
                    {compact && rescanButton}
                </CardFooter>
            )}
        </Card>
    )
}
