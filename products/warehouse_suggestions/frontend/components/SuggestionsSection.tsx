import { useActions, useValues } from 'kea'
import { ReactNode, useEffect, useRef } from 'react'

import { IconLightBulb } from '@posthog/icons'
import { LemonButton, LemonCollapse } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

const SECTION_KEY = 'suggestions'

export interface SuggestionsSectionProps {
    title: string
    summary: string
    children: ReactNode
}

export function SuggestionsSection({ title, summary, children }: SuggestionsSectionProps): JSX.Element {
    const { collapsed, status, stripState, moreSuggestionsCount, visibleSuggestions } =
        useValues(warehouseSuggestionsLogic)
    const { setCollapsed, showAllSuggestions } = useActions(warehouseSuggestionsLogic)
    const sectionRef = useRef<HTMLDivElement>(null)
    useFocusFollowsRemovedRow(
        sectionRef,
        visibleSuggestions.map((suggestion) => suggestion.id)
    )

    return (
        <div ref={sectionRef}>
            <LemonCollapse
                activeKey={collapsed ? null : SECTION_KEY}
                onChange={(activeKey) => setCollapsed(activeKey === null)}
                panels={[
                    {
                        key: SECTION_KEY,
                        dataAttr: 'warehouse-suggestions-collapse',
                        className: 'p-0',
                        header: (
                            <div className="flex min-w-0 flex-1 flex-wrap items-center justify-between gap-x-3 gap-y-1 py-0.5">
                                <div className="flex min-w-0 flex-col">
                                    <span className="flex items-center gap-1.5">
                                        <IconLightBulb className="shrink-0 text-secondary" />
                                        <span className="font-semibold">{title}</span>
                                    </span>
                                    {summary && <span className="text-xs font-normal text-secondary">{summary}</span>}
                                </div>
                                {status?.refreshed_at && (
                                    <span className="text-xs font-normal text-muted">
                                        <span>Refreshed </span>
                                        <TZLabel time={status.refreshed_at} showPopover={false} />
                                    </span>
                                )}
                            </div>
                        ),
                        content: (
                            <div className="@container/suggestions">
                                <div className="divide-y divide-primary">{children}</div>
                                {moreSuggestionsCount > 0 && (
                                    <div className="border-t border-primary px-2 py-1">
                                        <LemonButton
                                            size="xsmall"
                                            type="tertiary"
                                            onClick={() => showAllSuggestions()}
                                            data-attr="warehouse-suggestions-show-more"
                                        >
                                            {`Show ${moreSuggestionsCount} more`}
                                        </LemonButton>
                                    </div>
                                )}
                                {stripState === 'all_done' && (
                                    <div className="px-3 py-2.5 text-sm text-secondary">
                                        All caught up. New suggestions appear as reads build up.
                                    </div>
                                )}
                                <div className="border-t border-primary px-3 py-2 text-xs text-muted">
                                    Based on read counts from the query log. PostHog never reads your query text.
                                </div>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}

function useFocusFollowsRemovedRow(sectionRef: React.RefObject<HTMLDivElement>, rowIds: string[]): void {
    const previousRowIds = useRef(rowIds)

    useEffect(() => {
        const previous = previousRowIds.current
        previousRowIds.current = rowIds
        const removedIndex = previous.findIndex((id) => !rowIds.includes(id))
        const focusWasLost = !document.activeElement || document.activeElement === document.body
        if (removedIndex < 0 || !focusWasLost || !sectionRef.current) {
            return
        }
        const nextId = rowIds[removedIndex] ?? rowIds[removedIndex - 1]
        const target = nextId
            ? sectionRef.current.querySelector<HTMLElement>(
                  `[data-suggestion-row="${nextId}"] [data-suggestion-actions] button`
              )
            : sectionRef.current.querySelector<HTMLElement>('.LemonCollapsePanel__header')
        target?.focus()
    }, [rowIds, sectionRef])
}
