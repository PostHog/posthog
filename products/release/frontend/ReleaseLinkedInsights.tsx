import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'
import { Badge, Button, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { ReleaseRow } from './releaseUtils'

export function ReleaseLinkedInsights({ row }: { row: ReleaseRow }): JSX.Element | null {
    const { canEditReleases } = useValues(releaseLogic)
    const { relatedByRelease } = useValues(releaseRelatedLogic)
    const { unlinkRelated } = useActions(releaseRelatedLogic)
    const insights = relatedByRelease[row.id]?.insights ?? []

    if (!insights.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-1" data-attr="release-linked-insights">
            <Text size="xs" variant="muted">
                Insights
            </Text>
            <div className="-mx-2 flex flex-col">
                {insights.map((insight) => (
                    <div key={insight.id} className="group flex items-center rounded-md hover:bg-fill-hover">
                        <LinkPrimitive
                            to={urls.insightView(insight.shortId as never)}
                            className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1 text-foreground"
                            data-attr="release-linked-insight"
                        >
                            <span className="flex size-4 shrink-0 items-center justify-center text-muted-foreground [&_svg]:size-3.5">
                                {iconForType('insight/trends')}
                            </span>
                            <Text size="xs" className="truncate">
                                {insight.name}
                            </Text>
                            {insight.deleted && (
                                <Badge variant="warning" className="shrink-0">
                                    Deleted
                                </Badge>
                            )}
                        </LinkPrimitive>
                        {canEditReleases && (
                            <Button
                                size="icon-xs"
                                className="mr-1 shrink-0 opacity-0 focus-visible:opacity-100 group-hover:opacity-100"
                                aria-label={`Remove ${insight.name} from the release`}
                                tooltip="Remove from the release"
                                onClick={() => unlinkRelated(row.id, 'insight', String(insight.id))}
                                data-attr="release-linked-insight-remove"
                            >
                                <IconX />
                            </Button>
                        )}
                    </div>
                ))}
            </div>
        </div>
    )
}
