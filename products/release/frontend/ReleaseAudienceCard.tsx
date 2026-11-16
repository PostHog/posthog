import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { useState } from 'react'

import { IconCalendar, IconEllipsis, IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuTrigger,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Progress,
    ProgressLabel,
    ProgressValue,
    Separator,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { releaseLogic } from './releaseLogic'
import { ReleaseShowMore } from './ReleaseShowMore'
import { ReleaseFlagAudience, ReleaseRow, isEnrollingEarlyAccess, isExperimentRunning } from './releaseUtils'

function emptyVariantWarning(row: ReleaseRow, audience: ReleaseFlagAudience): string | null {
    const running = row.experiments.find(
        (experiment) => experiment.feature_flag_key === audience.flag.key && isExperimentRunning(experiment)
    )
    const groups =
        (
            (audience.flag.filters ?? {}) as {
                groups?: { variant?: string | null; rollout_percentage?: number | null }[]
            }
        ).groups ?? []
    const pinned = new Set(
        groups.filter((group) => group.variant && (group.rollout_percentage ?? 100) > 0).map((group) => group.variant)
    )
    const empty = audience.variants.filter((variant) => variant.percent === 0 && !pinned.has(variant.key))
    if (!running || !empty.length) {
        return null
    }
    return `${empty.map((variant) => variant.key).join(' and ')} get${empty.length === 1 ? 's' : ''} 0% of users, so ${running.name} has nothing to compare.`
}

function AudienceRow({ row, audience }: { row: ReleaseRow; audience: ReleaseFlagAudience }): JSX.Element {
    const { canEditReleases } = useValues(releaseLogic)
    const { openSchedule, unlinkFlag } = useActions(releaseLogic)
    const { flag } = audience
    const warning = emptyVariantWarning(row, audience)

    return (
        <div className="flex flex-col gap-2" data-attr="release-audience-row">
            <div className="flex min-w-0 items-center gap-2">
                <Button
                    variant="link-foreground"
                    size="sm"
                    nativeButton={false}
                    left
                    render={<LinkPrimitive to={urls.featureFlag(flag.id)} />}
                    className="min-w-0 shrink"
                    data-attr="release-audience-flag"
                >
                    <span className="truncate font-mono">{flag.key}</span>
                </Button>
                <Badge variant={flag.active ? 'success' : 'warning'}>{flag.active ? 'Enabled' : 'Disabled'}</Badge>
                <div className="ml-auto flex shrink-0 items-center gap-1">
                    <Button
                        size="icon-sm"
                        aria-label="Schedule a change"
                        tooltip="Schedule a change"
                        onClick={() => openSchedule(flag.id)}
                        data-attr="release-audience-schedule"
                    >
                        <IconCalendar />
                    </Button>
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon-sm"
                                    aria-label="More flag actions"
                                    tooltip="More flag actions"
                                    data-attr="release-flag-more"
                                />
                            }
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => router.actions.push(urls.featureFlag(flag.id))}>
                                Edit release conditions
                            </DropdownMenuItem>
                            {canEditReleases && (
                                <DropdownMenuItem
                                    variant="destructive"
                                    onClick={() => unlinkFlag(row.id, flag.id)}
                                    data-attr="release-flag-unlink"
                                >
                                    Remove from the release
                                </DropdownMenuItem>
                            )}
                        </DropdownMenuContent>
                    </DropdownMenu>
                </div>
            </div>
            {audience.percent !== null ? (
                <Progress
                    value={audience.percent}
                    variant={!flag.active ? 'warning' : audience.percent === 100 ? 'success' : 'default'}
                >
                    <ProgressLabel>{audience.who}</ProgressLabel>
                    <ProgressValue />
                </Progress>
            ) : (
                <Text size="xs" variant="muted">
                    {audience.summary}.
                </Text>
            )}
            {warning && (
                <Item variant="outline" tone="warning" size="sm" data-attr="release-variant-warning">
                    <ItemMedia variant="icon">
                        <IconWarning />
                    </ItemMedia>
                    <ItemContent>
                        <ItemTitle>The experiment cannot compare variants</ItemTitle>
                        <ItemDescription>{warning}</ItemDescription>
                    </ItemContent>
                    <ItemActions>
                        <Button
                            size="sm"
                            variant="outline"
                            nativeButton={false}
                            render={<LinkPrimitive to={urls.featureFlag(flag.id)} />}
                        >
                            Fix the split
                        </Button>
                    </ItemActions>
                </Item>
            )}
            {audience.variants.length > 0 && (
                <div className="flex flex-wrap items-center gap-1">
                    <Text size="xs" variant="muted">
                        Variants
                    </Text>
                    {audience.variants.map((variant) => (
                        <Badge key={variant.key}>{`${variant.key} ${variant.percent}%`}</Badge>
                    ))}
                </div>
            )}
        </div>
    )
}

const AUDIENCE_LIMIT = 5

export function ReleaseAudienceCard({ row }: { row: ReleaseRow }): JSX.Element {
    const [visible, setVisible] = useState(AUDIENCE_LIMIT)
    const openEarlyAccess = row.earlyAccess.find(isEnrollingEarlyAccess)

    return (
        <Card data-attr="release-flags">
            <CardHeader>
                <CardTitle>Who gets it now</CardTitle>
                <CardDescription>From the release conditions of each flag. Edit them on the flag.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
                {row.audiences.slice(0, visible).map((audience, index) => (
                    <div key={audience.flag.id} className="flex flex-col gap-4">
                        {index > 0 && <Separator />}
                        <AudienceRow row={row} audience={audience} />
                    </div>
                ))}
                <ReleaseShowMore
                    total={row.audiences.length}
                    visible={visible}
                    limit={AUDIENCE_LIMIT}
                    onChange={setVisible}
                    dataAttr="release-audience"
                />
                {openEarlyAccess && row.audiences.every((audience) => audience.percent !== null) && (
                    <Text size="xs" variant="muted">
                        {`Users can also opt in through ${openEarlyAccess.name}, now in ${openEarlyAccess.stage}.`}
                    </Text>
                )}
            </CardContent>
        </Card>
    )
}
