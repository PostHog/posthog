import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconWarning, IconX } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    Item,
    ItemActions,
    ItemContent,
    ItemDescription,
    ItemMedia,
    ItemTitle,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType } from '~/queries/schema/schema-general'
import { EarlyAccessFeatureStage } from '~/types'

import {
    getEarlyAccessFeatureStageLabel,
    getEarlyAccessFeatureStageTagType,
} from 'products/early_access_features/frontend/earlyAccessFeatureNotebookWidgetViews'
import { getExperimentStatus } from 'products/experiments/frontend/experimentStatus'
import {
    getExperimentStatusColor,
    getExperimentStatusLabel,
} from 'products/experiments/frontend/scenes/experimentsLogic'

import { ReleaseAddLinkCombobox } from './ReleaseAddLinkCombobox'
import { releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { ReleaseShowMore } from './ReleaseShowMore'
import { surveyStatus } from './releaseTracks'
import { ReleaseBadgeVariant, ReleaseRow, badgeVariantForTag } from './releaseUtils'

interface LinkedObject {
    key: string
    type: string
    title: string
    meta: string
    badge?: string
    badgeVariant: ReleaseBadgeVariant
    to: string
    onRemove?: () => void
}

function LinkedRow({ item }: { item: LinkedObject }): JSX.Element {
    return (
        <div className="group flex flex-row items-center rounded-md hover:bg-fill-hover">
            <LinkPrimitive
                to={item.to}
                className="flex w-full min-w-0 items-center gap-2.5 rounded-md px-2 py-1.5 text-start text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30"
                data-attr="release-linked-row"
            >
                <span className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4">
                    {iconForType(item.type as FileSystemIconType)}
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                    <Text size="xs" weight="medium" className="truncate">
                        {item.title}
                    </Text>
                    <Text size="xxs" variant="muted" className="truncate">
                        {item.meta}
                    </Text>
                </span>
                {item.badge && (
                    <Badge variant={item.badgeVariant} className="shrink-0">
                        {item.badge}
                    </Badge>
                )}
            </LinkPrimitive>
            {item.onRemove ? (
                <Button
                    variant="default"
                    size="icon-sm"
                    className="mr-1 shrink-0 opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
                    aria-label={`Remove ${item.title} from the release`}
                    onClick={item.onRemove}
                    data-attr="release-linked-remove"
                >
                    <IconX />
                </Button>
            ) : (
                <span className="mr-1 size-7 shrink-0" />
            )}
        </div>
    )
}

const LINKED_LIMIT = 8

export function ReleaseLinkedCard({ row }: { row: ReleaseRow }): JSX.Element {
    const [visible, setVisible] = useState(LINKED_LIMIT)
    const { canEditReleases } = useValues(releaseLogic)
    const { updateRelease, unlinkBroadcast } = useActions(releaseLogic)
    const { relatedByRelease } = useValues(releaseRelatedLogic)
    const { unlinkRelated } = useActions(releaseRelatedLogic)
    const related = relatedByRelease[row.id]
    const items: LinkedObject[] = [
        ...row.flags.map((flag) => ({
            key: `flag-${flag.id}`,
            type: 'feature_flag',
            title: flag.key,
            meta: 'Feature flag',
            badge: flag.active ? undefined : 'Disabled',
            badgeVariant: (flag.active ? 'success' : 'warning') as ReleaseBadgeVariant,
            to: urls.featureFlag(flag.id),
        })),
        ...row.experiments.map((experiment) => {
            const status = getExperimentStatus(experiment as never)
            return {
                key: `exp-${experiment.id}`,
                type: 'experiment',
                title: experiment.name,
                meta: 'Experiment',
                badge: getExperimentStatusLabel(status),
                badgeVariant: badgeVariantForTag(getExperimentStatusColor(status)),
                to: urls.experiment(experiment.id),
            }
        }),
        ...(related?.surveys ?? []).map((survey) => ({
            key: `survey-${survey.id}`,
            type: 'survey',
            title: survey.name,
            meta: 'Survey',
            badge: surveyStatus(survey),
            badgeVariant: (surveyStatus(survey) === 'Running' ? 'success' : 'default') as ReleaseBadgeVariant,
            to: urls.survey(survey.id),
            onRemove: canEditReleases ? () => unlinkRelated(row.id, 'survey', survey.id) : undefined,
        })),
        ...(related?.insights ?? []).map((insight) => ({
            key: `insight-${insight.id}`,
            type: 'insight/trends',
            title: insight.name,
            meta: 'Insight',
            badge: insight.deleted ? 'Deleted' : undefined,
            badgeVariant: 'warning' as ReleaseBadgeVariant,
            to: urls.insightView(insight.shortId as never),
            onRemove: canEditReleases ? () => unlinkRelated(row.id, 'insight', String(insight.id)) : undefined,
        })),
        ...row.broadcasts.map((broadcast) => ({
            key: `broadcast-${broadcast.id}`,
            type: 'broadcasts',
            title: broadcast.name || 'Untitled broadcast',
            meta: 'Broadcast',
            badge: (broadcast.status ?? 'draft').charAt(0).toUpperCase() + (broadcast.status ?? 'draft').slice(1),
            badgeVariant: broadcast.status === 'active' ? ('success' as const) : ('default' as const),
            to: urls.broadcast(broadcast.id),
            onRemove: canEditReleases ? () => unlinkBroadcast(row.id, broadcast.id) : undefined,
        })),
        ...row.earlyAccess.map((item) => {
            const stage = item.stage as EarlyAccessFeatureStage
            return {
                key: `ea-${item.id}`,
                type: 'early_access_feature',
                title: item.name,
                meta: 'Early access feature',
                badge: getEarlyAccessFeatureStageLabel(stage),
                badgeVariant: badgeVariantForTag(getEarlyAccessFeatureStageTagType(stage)),
                to: urls.earlyAccessFeature(item.id),
            }
        }),
    ]

    const shown = items.slice(0, visible)

    return (
        <Card size="sm" data-attr="release-linked">
            <CardHeader>
                <CardTitle>In this release</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                {row.missingFlagIds.length > 0 && (
                    <Item variant="outline" tone="warning" size="sm" data-attr="release-missing-flags">
                        <ItemMedia variant="icon">
                            <IconWarning />
                        </ItemMedia>
                        <ItemContent>
                            <ItemTitle>
                                {row.missingFlagIds.length === 1
                                    ? 'A linked flag was deleted'
                                    : `${row.missingFlagIds.length} linked flags were deleted`}
                            </ItemTitle>
                            <ItemDescription>
                                {row.missingFlagIds.length === 1
                                    ? 'Remove it, or link the flag that replaced it.'
                                    : 'Remove them, or link the flags that replaced them.'}
                            </ItemDescription>
                        </ItemContent>
                        {canEditReleases && (
                            <ItemActions>
                                <Button
                                    size="sm"
                                    variant="outline"
                                    onClick={() =>
                                        updateRelease(row.id, { feature_flag_ids: row.flags.map((flag) => flag.id) })
                                    }
                                >
                                    Remove
                                </Button>
                            </ItemActions>
                        )}
                    </Item>
                )}
                {items.length > 0 ? (
                    <div className="-mx-2 flex flex-col">
                        {shown.map((item) => (
                            <LinkedRow key={item.key} item={item} />
                        ))}
                    </div>
                ) : (
                    <Text size="xs" variant="muted">
                        Nothing linked yet.
                    </Text>
                )}
                <ReleaseShowMore
                    total={items.length}
                    visible={visible}
                    limit={LINKED_LIMIT}
                    onChange={setVisible}
                    dataAttr="release-linked"
                />
                {canEditReleases && <ReleaseAddLinkCombobox row={row} />}
            </CardContent>
        </Card>
    )
}
