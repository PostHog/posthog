// PROTOTYPE (throwaway): the overview's filters: the period, marketing or transactional topics (or single topics),
// and the channel.
import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuRadioItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    ToggleGroup,
    ToggleGroupItem,
} from '@posthog/quill'

import { ChannelFilter, OverviewFilterState, PERIODS, Period, TOPICS, TopicKind } from './insightsData'

const CHANNELS: { value: ChannelFilter; label: string }[] = [
    { value: 'all', label: 'All channels' },
    { value: 'email', label: 'Email' },
    { value: 'sms', label: 'SMS' },
    { value: 'push', label: 'Push' },
]

const KIND_LABEL: Record<TopicKind, string> = {
    all: 'All topics',
    marketing: 'Marketing',
    transactional: 'Transactional',
}

function topicsLabel(filters: OverviewFilterState): string {
    if (filters.topics.length === 1) {
        return TOPICS.find((t) => t.key === filters.topics[0])?.label ?? 'All topics'
    }
    if (filters.topics.length > 1) {
        return `${filters.topics.length} topics`
    }
    return KIND_LABEL[filters.topicKind]
}

export function OverviewFilterBar({
    filters,
    onChange,
}: {
    filters: OverviewFilterState
    onChange: (filters: OverviewFilterState) => void
}): JSX.Element {
    const visibleTopics = TOPICS.filter((t) => filters.topicKind === 'all' || t.kind === filters.topicKind)
    return (
        <div className="flex flex-wrap items-center gap-2">
            <DropdownMenu>
                <DropdownMenuTrigger render={<Button variant="outline" />}>
                    {PERIODS.find((p) => p.value === filters.period)?.label}
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start">
                    <DropdownMenuRadioGroup
                        value={String(filters.period)}
                        onValueChange={(value) => onChange({ ...filters, period: Number(value) as Period })}
                    >
                        {PERIODS.map((p) => (
                            <DropdownMenuRadioItem key={p.value} value={String(p.value)}>
                                {p.label}
                            </DropdownMenuRadioItem>
                        ))}
                    </DropdownMenuRadioGroup>
                </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
                <DropdownMenuTrigger render={<Button variant="outline" />}>
                    {topicsLabel(filters)}
                    <IconChevronDown />
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" className="min-w-56">
                    <DropdownMenuRadioGroup
                        value={filters.topicKind}
                        onValueChange={(value) => onChange({ ...filters, topicKind: value as TopicKind, topics: [] })}
                    >
                        <DropdownMenuRadioItem value="all">All topics</DropdownMenuRadioItem>
                        <DropdownMenuRadioItem value="marketing">Marketing</DropdownMenuRadioItem>
                        <DropdownMenuRadioItem value="transactional">Transactional</DropdownMenuRadioItem>
                    </DropdownMenuRadioGroup>
                    <DropdownMenuSeparator />
                    <DropdownMenuGroup>
                        <DropdownMenuLabel>Topics</DropdownMenuLabel>
                        {visibleTopics.map((t) => (
                            <DropdownMenuCheckboxItem
                                key={t.key}
                                checked={filters.topics.includes(t.key)}
                                closeOnClick={false}
                                onCheckedChange={(checked) =>
                                    onChange({
                                        ...filters,
                                        topics: checked
                                            ? [...filters.topics, t.key]
                                            : filters.topics.filter((key) => key !== t.key),
                                    })
                                }
                            >
                                {t.label}
                            </DropdownMenuCheckboxItem>
                        ))}
                    </DropdownMenuGroup>
                </DropdownMenuContent>
            </DropdownMenu>
            <ToggleGroup
                variant="outline"
                aria-label="Channel"
                value={[filters.channel]}
                onValueChange={(next: string[]) =>
                    next[0] && onChange({ ...filters, channel: next[0] as ChannelFilter })
                }
            >
                {CHANNELS.map((c) => (
                    <ToggleGroupItem key={c.value} value={c.value}>
                        {c.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}
