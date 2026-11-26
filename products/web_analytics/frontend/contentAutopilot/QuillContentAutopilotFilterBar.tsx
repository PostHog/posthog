import { Button, Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Text } from '@posthog/quill'

import { AiVisibilityDateFilter } from './AiVisibilityDateFilter'
import type { AiVisibilityFilter, AiVisibilityFilterTab } from './aiVisibilityFilters'
import { ContentAutopilotBrandedSegmentControl } from './ContentAutopilotBrandedSegmentControl'
import type { FilterOption } from './contentAutopilotFilterBarLogic'

// A quill Select reads a null value as nothing chosen, so the "All …" option, whose value is null, gets a key of its own.
const ALL = '__all__'
const toKey = (value: string | null): string => value ?? ALL
const fromKey = (key: string): string | null => (key === ALL ? null : key)

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

export interface QuillContentAutopilotFilterBarProps {
    tab: AiVisibilityFilterTab
    filters: readonly AiVisibilityFilter[]
    engine: string | null
    engineOptions: FilterOption[]
    onEngineChange: (engine: string | null) => void
    topicValue: string | null
    topicOptions: FilterOption[]
    onTopicChange: (topic: string | null) => void
    promptTopicsError: boolean
    promptTopicsLoading: boolean
    onRetryTopics: () => void
}

export const QuillContentAutopilotFilterBar = ({
    tab,
    filters,
    engine,
    engineOptions,
    onEngineChange,
    topicValue,
    topicOptions,
    onTopicChange,
    promptTopicsError,
    promptTopicsLoading,
    onRetryTopics,
}: QuillContentAutopilotFilterBarProps): JSX.Element => {
    return (
        <div className="flex flex-wrap items-center gap-2" data-attr={`content-autopilot-${tab}-filters`}>
            {filters.includes('dateRange') ? <AiVisibilityDateFilter tab={tab} /> : null}
            {filters.includes('engine') ? (
                <FilterSelect
                    label="Engine"
                    value={engine}
                    options={engineOptions}
                    onChange={onEngineChange}
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
                            onClick={onRetryTopics}
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
                        onChange={onTopicChange}
                        dataAttr={`content-autopilot-${tab}-topic-filter`}
                    />
                )
            ) : null}
            {filters.includes('branded') ? <ContentAutopilotBrandedSegmentControl tab={tab} /> : null}
        </div>
    )
}
