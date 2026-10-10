import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Button, Text } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import { isActionsNode, isEventsNode, isGroupNode } from '~/queries/utils'
import type { InsightLogicProps } from '~/types'

import { EditableWord } from './EditableWord'
import { EventPickerPopover } from './EventPickerPopover'
import { insightSentenceLogic } from './insightSentenceLogic'
import { SentenceEventActions } from './SentenceEventActions'
import { SeriesRenameInput } from './SeriesRenameInput'

export function SentenceEvent({
    insightProps,
    seriesIndex,
    label,
}: {
    insightProps: InsightLogicProps
    seriesIndex: number
    label: string
}): JSX.Element {
    const { trendsQuery, seriesColors, renamingSeriesIndex } = useValues(insightSentenceLogic(insightProps))
    const {
        changeSeriesEvent,
        combineSeriesEvent,
        duplicateSeries,
        removeSeries,
        renameSeries,
        setPendingFilterSeriesIndex,
        setRenamingSeriesIndex,
        splitCombinedSeries,
    } = useActions(insightSentenceLogic(insightProps))
    // The picker then adds its pick to this event instead of replacing the event.
    const [combining, setCombining] = useState(false)

    const node = trendsQuery?.series[seriesIndex]
    const seriesCount = trendsQuery?.series.length ?? 0
    const isCombined = !!node && isGroupNode(node)
    const groupType = node && isActionsNode(node) ? TaxonomicFilterGroupType.Actions : TaxonomicFilterGroupType.Events
    const value = node && isActionsNode(node) ? node.id : node && isEventsNode(node) ? node.event : undefined

    if (renamingSeriesIndex === seriesIndex) {
        return (
            <SeriesRenameInput
                initialName={label}
                onSave={(name) => {
                    if (name.trim() === label) {
                        setRenamingSeriesIndex(null)
                    } else {
                        renameSeries(seriesIndex, name)
                    }
                }}
                onCancel={() => setRenamingSeriesIndex(null)}
            />
        )
    }

    return (
        <EventPickerPopover
            groupType={groupType}
            value={combining || isCombined ? undefined : value}
            onPick={(pickedGroupType, pickedValue, name) =>
                combining
                    ? combineSeriesEvent(seriesIndex, pickedGroupType, pickedValue, name)
                    : changeSeriesEvent(seriesIndex, pickedGroupType, pickedValue, name)
            }
            onClose={() => setCombining(false)}
            footer={(close) =>
                combining ? (
                    <div className="flex items-center justify-between gap-2">
                        <Text size="xs" variant="muted">
                            {`Pick an event to count together with ${label}.`}
                        </Text>
                        <Button
                            variant="outline"
                            size="sm"
                            onMouseDown={(event: React.MouseEvent) => event.preventDefault()}
                            onClick={() => setCombining(false)}
                            data-attr="quill-insight-event-action-combine-cancel"
                        >
                            Cancel
                        </Button>
                    </div>
                ) : (
                    <SentenceEventActions
                        onFilter={
                            seriesCount > 1
                                ? () => {
                                      close()
                                      setPendingFilterSeriesIndex(seriesIndex)
                                  }
                                : null
                        }
                        onRename={() => {
                            close()
                            setRenamingSeriesIndex(seriesIndex)
                        }}
                        onDuplicate={() => {
                            close()
                            duplicateSeries(seriesIndex)
                        }}
                        onCombine={() => setCombining(true)}
                        onSplitApart={
                            isCombined
                                ? () => {
                                      close()
                                      splitCombinedSeries(seriesIndex)
                                  }
                                : null
                        }
                        onRemove={
                            seriesCount > 1
                                ? () => {
                                      close()
                                      removeSeries(seriesIndex)
                                  }
                                : null
                        }
                    />
                )
            }
            trigger={(open, toggle) => (
                <EditableWord
                    color="blue"
                    aria-expanded={open}
                    onClick={toggle}
                    lineColor={seriesColors[seriesIndex] ?? undefined}
                    data-attr="quill-insight-sentence-event"
                >
                    {label}
                </EditableWord>
            )}
        />
    )
}
