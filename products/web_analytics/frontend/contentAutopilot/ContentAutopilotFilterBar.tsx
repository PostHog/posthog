import { useActions, useValues } from 'kea'

import { LemonButton, LemonSelect } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { AiVisibilityDateFilter } from './AiVisibilityDateFilter'
import { type AiVisibilityFilter, type AiVisibilityFilterTab } from './aiVisibilityFilters'
import { ContentAutopilotBrandedSegmentControl } from './ContentAutopilotBrandedSegmentControl'
import { contentAutopilotFilterBarLogic } from './contentAutopilotFilterBarLogic'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'
import { QuillContentAutopilotFilterBar } from './QuillContentAutopilotFilterBar'

export const ContentAutopilotFilterBar = ({
    tab,
    filters,
}: {
    tab: AiVisibilityFilterTab
    filters: readonly AiVisibilityFilter[]
}): JSX.Element => {
    const { engine } = useValues(contentAutopilotFiltersLogic)
    const { setEngine, setTopic } = useActions(contentAutopilotFiltersLogic)
    const { engineOptions, topicOptions, topicValue, promptTopicsError, promptTopicsLoading } =
        useValues(contentAutopilotFilterBarLogic)
    const { loadPromptTopics } = useActions(contentAutopilotFilterBarLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    if (todayRailNav) {
        return (
            <QuillContentAutopilotFilterBar
                tab={tab}
                filters={filters}
                engine={engine}
                engineOptions={engineOptions}
                onEngineChange={(value) => setEngine(value, tab)}
                topicValue={topicValue}
                topicOptions={topicOptions}
                onTopicChange={(value) => setTopic(value, tab)}
                promptTopicsError={promptTopicsError}
                promptTopicsLoading={promptTopicsLoading}
                onRetryTopics={loadPromptTopics}
            />
        )
    }

    return (
        <div className="flex flex-wrap items-center gap-2" data-attr={`content-autopilot-${tab}-filters`}>
            {filters.includes('dateRange') ? <AiVisibilityDateFilter tab={tab} /> : null}
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
                        value={topicValue}
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
