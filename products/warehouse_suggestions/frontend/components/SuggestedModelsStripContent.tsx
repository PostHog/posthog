import { useActions, useValues } from 'kea'

import { IconChevronDown, IconInfo, IconSparkles } from '@posthog/icons'
import { LemonButton, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'
import { cn } from 'lib/utils/css-classes'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { MaterializeSuggestionCard } from './MaterializeSuggestionCard'
import { MaterializeSuggestionModal } from './MaterializeSuggestionModal'

const COLLAPSED_NAME_PREVIEW = 2

export function SuggestedModelsStripContent(): JSX.Element | null {
    const { stripState, surfaceSuggestions, collapsed, status } = useValues(warehouseSuggestionsLogic)
    const { setCollapsed, reload } = useActions(warehouseSuggestionsLogic)

    if (stripState === 'loading' || stripState === 'hidden') {
        return null
    }
    const windowDays = status?.window_days ?? 0
    const names = surfaceSuggestions.map((suggestion) => suggestion.payload.subject_name)
    const extraNames = names.length - COLLAPSED_NAME_PREVIEW

    return (
        <section className="flex flex-col gap-3 rounded border border-primary bg-surface-secondary p-3">
            <div className="flex flex-wrap items-start gap-x-3 gap-y-2">
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <div className="flex items-center gap-1.5">
                        <IconSparkles className="text-secondary" />
                        <h3 className="m-0 text-sm font-semibold">Suggested models</h3>
                        {names.length > 0 && <span className="text-xs tabular-nums text-muted">{names.length}</span>}
                        <Tooltip title="PostHog suggests models from how this project reads its views and tables. It counts reads only and never reads your query text. Dismiss a suggestion to stop seeing it.">
                            <IconInfo className="text-secondary" />
                        </Tooltip>
                    </div>
                    <span className="text-xs text-muted">
                        <span>Based on read counts only. We never read your query text.</span>
                        {status?.refreshed_at && <span>{` Refreshed ${dayjs(status.refreshed_at).fromNow()}.`}</span>}
                    </span>
                </div>
                {stripState === 'active' && (
                    <LemonButton
                        size="xsmall"
                        icon={<IconChevronDown className={cn('transition-transform', collapsed && '-rotate-90')} />}
                        onClick={() => setCollapsed(!collapsed)}
                        aria-label={collapsed ? 'Show suggested models' : 'Hide suggested models'}
                        data-attr="warehouse-suggestions-collapse"
                    />
                )}
            </div>
            {stripState === 'error' && (
                <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span>Couldn't load suggestions.</span>
                    <LemonButton size="xsmall" type="secondary" onClick={() => reload()}>
                        Retry
                    </LemonButton>
                </div>
            )}
            {stripState === 'warming_up' && (
                <span className="text-sm text-secondary">
                    {`Suggestions get better as read history builds up. This project has ${status?.days_with_data} of ${windowDays} days so far.`}
                </span>
            )}
            {stripState === 'not_eligible' && (
                <span className="text-sm text-secondary">
                    Suggestions start once people in this project read its views regularly.
                </span>
            )}
            {stripState === 'active' && collapsed && (
                <span className="truncate text-xs text-secondary">
                    <span translate="no">{names.slice(0, COLLAPSED_NAME_PREVIEW).join(', ')}</span>
                    {extraNames > 0 && <span>{` and ${extraNames} more`}</span>}
                </span>
            )}
            {stripState === 'active' && !collapsed && (
                <div className="@container">
                    <div className="grid grid-cols-1 gap-2 @min-[37.5rem]:grid-cols-2">
                        {surfaceSuggestions.map((suggestion) => (
                            <MaterializeSuggestionCard
                                key={suggestion.id}
                                suggestion={suggestion}
                                windowDays={windowDays}
                            />
                        ))}
                    </div>
                </div>
            )}
            <MaterializeSuggestionModal />
        </section>
    )
}
