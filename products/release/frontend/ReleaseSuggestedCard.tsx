import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconX } from '@posthog/icons'
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle, Skeleton, Text } from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { linkSuggestionsKey, releaseLogic } from './releaseLogic'
import { releaseRelatedLogic } from './releaseRelatedLogic'
import { ReleaseShowMore } from './ReleaseShowMore'
import { linkedKeys } from './releaseTracks'
import { ReleaseRow } from './releaseUtils'

const GROUP_LIMIT = 3

interface Suggestion {
    key: string
    icon: 'feature_flag' | 'broadcasts' | 'survey' | 'insight/trends'
    label: string
    reason: string
    to?: string
    add: () => void
}

function SuggestionRow({ item, onDismiss }: { item: Suggestion; onDismiss: () => void }): JSX.Element {
    return (
        <div className="group flex min-w-0 items-start gap-2.5 rounded-md px-2 py-1.5 hover:bg-fill-hover">
            <span className="mt-0.5 flex size-4 shrink-0 items-center justify-center [&_svg]:size-4">
                {iconForType(item.icon)}
            </span>
            <span className="flex min-w-0 flex-1 flex-col">
                {item.to ? (
                    <LinkPrimitive
                        to={item.to}
                        target="_blank"
                        className="truncate text-xs font-medium text-foreground hover:underline"
                    >
                        {item.label}
                    </LinkPrimitive>
                ) : (
                    <Text size="xs" weight="medium" className="truncate">
                        {item.label}
                    </Text>
                )}
                <Text size="xxs" variant="muted" className="truncate">
                    {item.reason}
                </Text>
            </span>
            <Button
                size="xs"
                variant="outline"
                onClick={item.add}
                aria-label={`Add ${item.label}`}
                data-attr="release-suggested-add"
            >
                Add
            </Button>
            <Button
                size="icon-xs"
                variant="default"
                aria-label={`Dismiss ${item.label}`}
                onClick={onDismiss}
                data-attr="release-suggested-dismiss"
            >
                <IconX />
            </Button>
        </div>
    )
}

function Group({
    title,
    items,
    onDismiss,
    dataAttr,
}: {
    title: string
    items: Suggestion[]
    onDismiss: (key: string) => void
    dataAttr: string
}): JSX.Element | null {
    const [visible, setVisible] = useState(GROUP_LIMIT)
    if (!items.length) {
        return null
    }
    return (
        <div className="flex flex-col gap-0.5" data-attr={dataAttr}>
            <Text size="xxs" weight="semibold" variant="muted" className="px-2 uppercase tracking-wide">
                {`${title} · ${items.length}`}
            </Text>
            {items.slice(0, visible).map((item) => (
                <SuggestionRow key={item.key} item={item} onDismiss={() => onDismiss(item.key)} />
            ))}
            <div className="px-2">
                <ReleaseShowMore
                    total={items.length}
                    visible={visible}
                    limit={GROUP_LIMIT}
                    onChange={setVisible}
                    dataAttr={dataAttr}
                />
            </div>
        </div>
    )
}

export function ReleaseSuggestedCard({ row }: { row: ReleaseRow }): JSX.Element | null {
    const { canEditReleases, linkSuggestions: loaded, linkSuggestionsFor } = useValues(releaseLogic)
    const { loadLinkSuggestions, addLink } = useActions(releaseLogic)
    const { relatedSuggestions, relatedSuggestionsLoading, dismissed, insightsById, relatedByRelease } =
        useValues(releaseRelatedLogic)
    const { loadRelatedSuggestions, linkRelated, dismissSuggestion } = useActions(releaseRelatedLogic)

    const flagKeys = row.flags.map((flag) => flag.key).join(',')
    useEffect(() => {
        if (!canEditReleases) {
            return
        }
        loadLinkSuggestions(row.id)
        loadRelatedSuggestions(row)
    }, [row.id, row.name, flagKeys, canEditReleases])

    if (!canEditReleases) {
        return null
    }

    const related = relatedByRelease[row.id]
    const linked = linkedKeys(row, related)
    const visible = (key: string): boolean => !dismissed[`${row.id}:${key}`] && !linked.has(key)

    const relatedItems: (Suggestion & { detected: boolean })[] =
        relatedSuggestions?.releaseId === row.id
            ? relatedSuggestions.items.map((item) => ({
                  key: item.key,
                  icon: item.kind === 'survey' ? 'survey' : 'insight/trends',
                  label: item.label,
                  reason: item.reason,
                  detected: item.detected,
                  to:
                      item.kind === 'survey'
                          ? urls.survey(item.id)
                          : insightsById[Number(item.id)]
                            ? urls.insightView(insightsById[Number(item.id)].shortId as never)
                            : undefined,
                  add: () => linkRelated(row.id, item.kind, item.id),
              }))
            : []
    const linkItems: Suggestion[] = (linkSuggestionsFor === linkSuggestionsKey(row) ? loaded : []).map((candidate) => ({
        key: candidate.key,
        icon: candidate.kind === 'flag' ? 'feature_flag' : 'broadcasts',
        label: candidate.label,
        reason: 'Name matches this release',
        add: () => addLink(row.id, candidate),
    }))

    const found = relatedItems.filter((item) => item.detected && visible(item.key))
    const maybe = [...linkItems, ...relatedItems.filter((item) => !item.detected)].filter((item) => visible(item.key))
    const loading = relatedSuggestionsLoading && relatedSuggestions?.releaseId !== row.id

    const failed = relatedSuggestions?.releaseId === row.id && relatedSuggestions.failed

    if (!loading && !found.length && !maybe.length && !failed) {
        return null
    }

    return (
        <Card size="sm" data-attr="release-suggested">
            <CardHeader>
                <CardTitle>Suggested</CardTitle>
                <CardDescription>Things in your project that look like part of this release.</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
                {loading ? (
                    <div className="flex flex-col gap-2">
                        <Skeleton className="h-8 w-full" />
                        <Skeleton className="h-8 w-full" />
                    </div>
                ) : (
                    <>
                        <Group
                            key={`found-${row.id}`}
                            title="Uses this release's flags"
                            items={found}
                            onDismiss={(key) => dismissSuggestion(row.id, key)}
                            dataAttr="release-suggested-found"
                        />
                        <Group
                            key={`maybe-${row.id}`}
                            title="Similar name"
                            items={maybe}
                            onDismiss={(key) => dismissSuggestion(row.id, key)}
                            dataAttr="release-suggested-maybe"
                        />
                        {failed && (
                            <div
                                className="flex items-center justify-between gap-2 px-2"
                                data-attr="release-suggested-failed"
                            >
                                <Text size="xs" variant="muted">
                                    Some suggestions could not load.
                                </Text>
                                <Button
                                    size="xs"
                                    variant="link-muted"
                                    onClick={() => loadRelatedSuggestions(row)}
                                    disabled={relatedSuggestionsLoading}
                                    loading={relatedSuggestionsLoading}
                                    data-attr="release-suggested-retry"
                                >
                                    Try again
                                </Button>
                            </div>
                        )}
                    </>
                )}
            </CardContent>
        </Card>
    )
}
