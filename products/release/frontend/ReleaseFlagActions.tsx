import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCalendar, IconEllipsis, IconWarning } from '@posthog/icons'
import {
    Button,
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
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import type { FeatureFlagApi } from 'products/feature_flags/frontend/generated/api.schemas'

import { releaseLogic } from './releaseLogic'
import { ReleaseFlagAudience, ReleaseRow, isExperimentRunning } from './releaseUtils'

export function emptyVariantWarning(row: ReleaseRow, audience: ReleaseFlagAudience): string | null {
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

export function ReleaseVariantWarning({ flag, warning }: { flag: FeatureFlagApi; warning: string }): JSX.Element {
    return (
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
    )
}

export function ReleaseFlagActions({ row, flag }: { row: ReleaseRow; flag: FeatureFlagApi }): JSX.Element {
    const { canEditReleases } = useValues(releaseLogic)
    const { openSchedule, unlinkFlag } = useActions(releaseLogic)

    return (
        <div className="flex shrink-0 items-center gap-0.5">
            <Button
                size="icon-xs"
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
                            size="icon-xs"
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
    )
}
