import { useActions, useValues } from 'kea'

import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Text } from '@posthog/quill'

import { AiVisibilityDateFilter } from './AiVisibilityDateFilter'
import type { AiVisibilityFilter, AiVisibilityFilterTab } from './aiVisibilityFilters'
import { ContentAutopilotBrandedSegmentControl } from './ContentAutopilotBrandedSegmentControl'
import { contentAutopilotFilterBarLogic, type FilterOption } from './contentAutopilotFilterBarLogic'
import { contentAutopilotFiltersLogic } from './contentAutopilotFiltersLogic'

// A quill Select reads a null value as nothing chosen, so the "All …" option, whose value is null, gets a key of its own.
// Every real value takes a prefix, so no topic name can collide with that key.
const ALL = 'all'
const VALUE_PREFIX = 'value:'
const toKey = (value: string | null): string => (value === null ? ALL : `${VALUE_PREFIX}${value}`)
const fromKey = (key: string): string | null => (key === ALL ? null : key.slice(VALUE_PREFIX.length))

const FilterSelect = ({
    label,
    value,
    options,
    onChange,
    dataAttr,
}: {
    label: string
    value: string | null
    options: FilterOption[]
    onChange: (value: string | null) => void
    dataAttr: string
}): JSX.Element => (
    <Select<string> value={toKey(value)} onValueChange={(key) => key !== null && onChange(fromKey(key))}>
        <SelectTrigger aria-label={label} data-attr={dataAttr}>
            <SelectValue>
                {(key: string | null) => options.find((option) => toKey(option.value) === key)?.label}
            </SelectValue>
        </SelectTrigger>
        <SelectContent>
            {options.map((option) => (
                <SelectItem key={toKey(option.value)} value={toKey(option.value)}>
                    {option.label}
                </SelectItem>
            ))}
        </SelectContent>
    </Select>
)

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

    return (
        <div className="flex flex-wrap items-center gap-2" data-attr={`content-autopilot-${tab}-filters`}>
            {filters.includes('dateRange') ? <AiVisibilityDateFilter tab={tab} /> : null}
            {filters.includes('engine') ? (
                <FilterSelect
                    label="Engine"
                    value={engine}
                    options={engineOptions}
                    onChange={(value) => setEngine(value, tab)}
                    dataAttr={`content-autopilot-${tab}-engine-filter`}
                />
            ) : null}
            {filters.includes('topic') ? (
                promptTopicsError ? (
                    <span className="flex items-center gap-1">
                        <Text size="xs" render={<span className="m-0 text-destructive-foreground" />}>
                            Couldn't load topics.
                        </Text>
                        <Button
                            variant="outline"
                            size="sm"
                            onClick={loadPromptTopics}
                            loading={promptTopicsLoading}
                            data-attr={`content-autopilot-${tab}-topics-retry`}
                        >
                            Try again
                        </Button>
                    </span>
                ) : (
                    <FilterSelect
                        label="Topic"
                        value={topicValue}
                        options={topicOptions}
                        onChange={(value) => setTopic(value, tab)}
                        dataAttr={`content-autopilot-${tab}-topic-filter`}
                    />
                )
            ) : null}
            {filters.includes('branded') ? <ContentAutopilotBrandedSegmentControl tab={tab} /> : null}
        </div>
    )
}
