import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { DateFilter } from 'lib/components/DateFilter/DateFilter'

import {
    AI_VISIBILITY_DAYS_OPTIONS,
    type AiVisibilityFilter,
    type AiVisibilityFilterTab,
    dateFromToDays,
    daysToDateFrom,
} from './aiVisibilityFilters'
import { ContentAutopilotBrandedSegmentControl } from './ContentAutopilotBrandedSegmentControl'
import { contentAutopilotFilterBarLogic } from './contentAutopilotFilterBarLogic'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'

const DATE_OPTIONS = AI_VISIBILITY_DAYS_OPTIONS.map((days) => ({
    key: `Last ${days} days`,
    values: [daysToDateFrom(days)],
}))

export const ContentAutopilotFilterBar = ({
    tab,
    filters,
}: {
    tab: AiVisibilityFilterTab
    filters: readonly AiVisibilityFilter[]
}): JSX.Element => {
    const { days, engine, topic } = useValues(contentAutopilotFiltersLogic)
    const { setDays, setEngine, setTopic } = useActions(contentAutopilotFiltersLogic)
    const { engineOptions, topicOptions, promptTopicsError, promptTopicsLoading } =
        useValues(contentAutopilotFilterBarLogic)
    const { loadPromptTopics } = useActions(contentAutopilotFilterBarLogic)

    return (
        <div className="flex flex-wrap items-center gap-2" data-attr={`content-autopilot-${tab}-filters`}>
            {filters.includes('dateRange') ? (
                <DateFilter
                    size="small"
                    dateFrom={daysToDateFrom(days)}
                    dateTo={null}
                    dateOptions={DATE_OPTIONS}
                    showCustom={false}
                    showRollingRangePicker={false}
                    onChange={(dateFrom) => {
                        const next = dateFromToDays(dateFrom)
                        if (next !== null) {
                            setDays(next, tab)
                        }
                    }}
                />
            ) : null}
            {filters.includes('engine') ? (
                <LemonSelect
                    size="small"
                    aria-label="Engine"
                    value={engine}
                    onChange={(value) => setEngine(value, tab)}
                    options={engineOptions}
                    data-attr={`content-autopilot-${tab}-engine-filter`}
                />
            ) : null}
            {filters.includes('topic') ? (
                promptTopicsError ? (
                    <span className="flex items-center gap-1 text-danger text-sm">
                        Couldn't load topics.
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            onClick={loadPromptTopics}
                            loading={promptTopicsLoading}
                            data-attr={`content-autopilot-${tab}-topics-retry`}
                        >
                            Try again
                        </LemonButton>
                    </span>
                ) : (
                    <LemonSelect
                        size="small"
                        aria-label="Topic"
                        value={topic}
                        onChange={(value) => setTopic(value, tab)}
                        options={topicOptions}
                        data-attr={`content-autopilot-${tab}-topic-filter`}
                    />
                )
            ) : null}
            {filters.includes('branded') ? <ContentAutopilotBrandedSegmentControl tab={tab} /> : null}
        </div>
    )
}
