import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconWarning } from '@posthog/icons'
import {
    Badge,
    Button,
    Card,
    CardContent,
    CardGroup,
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

import { ReleaseLinkFlagCombobox } from './ReleaseLinkFlagCombobox'
import { releaseLogic } from './releaseLogic'
import { ReleaseShowMore } from './ReleaseShowMore'
import { ReleaseBadgeVariant, ReleaseRow, badgeVariantForTag } from './releaseUtils'

interface LinkedObject {
    key: string
    type: string
    title: string
    meta: string
    badge: string
    badgeVariant: ReleaseBadgeVariant
    to: string
    mono?: boolean
}

function LinkedRow({ item }: { item: LinkedObject }): JSX.Element {
    return (
        <Card size="sm" className="p-0">
            <LinkPrimitive
                to={item.to}
                className="flex w-full min-w-0 items-center gap-2.5 px-3 py-2 text-start text-foreground hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring/30"
                data-attr="release-linked-row"
            >
                <span className="flex size-4 shrink-0 items-center justify-center [&_svg]:size-4">
                    {iconForType(item.type as FileSystemIconType)}
                </span>
                <span className="flex min-w-0 flex-1 flex-col">
                    <Text size="xs" weight="medium" className={item.mono ? 'truncate font-mono' : 'truncate'}>
                        {item.title}
                    </Text>
                    <Text size="xxs" variant="muted" className="truncate">
                        {item.meta}
                    </Text>
                </span>
                <Badge variant={item.badgeVariant} className="shrink-0">
                    {item.badge}
                </Badge>
            </LinkPrimitive>
        </Card>
    )
}

const LINKED_LIMIT = 8

export function ReleaseLinkedCard({ row }: { row: ReleaseRow }): JSX.Element {
    const [visible, setVisible] = useState(LINKED_LIMIT)
    const { canEditReleases } = useValues(releaseLogic)
    const { updateRelease } = useActions(releaseLogic)
    const items: LinkedObject[] = [
        ...row.flags.map((flag) => ({
            key: `flag-${flag.id}`,
            type: 'feature_flag',
            title: flag.key,
            meta: 'Feature flag',
            badge: flag.active ? 'Enabled' : 'Disabled',
            badgeVariant: (flag.active ? 'success' : 'warning') as ReleaseBadgeVariant,
            to: urls.featureFlag(flag.id),
            mono: true,
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
                    <CardGroup>
                        {shown.map((item) => (
                            <LinkedRow key={item.key} item={item} />
                        ))}
                    </CardGroup>
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
                {row.flags.length > 0 && canEditReleases && (
                    <ReleaseLinkFlagCombobox row={row} placeholder="Link another flag" />
                )}
            </CardContent>
        </Card>
    )
}
