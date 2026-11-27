import { useActions, useValues } from 'kea'

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue, Skeleton, Text } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityCard } from './AiVisibilityCard'
import { AiVisibilityTable } from './AiVisibilityTable'
import { AiVisibilityTag } from './AiVisibilityTag'
import { ContentAutopilotKeywordModifierTerms } from './ContentAutopilotKeywordModifierTerms'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { type ModifierGroup, isCitationGap, modifierGroups } from './keywordsReport'
import { windowRange } from './utils'

// Select items need a string value, and no keyword is empty.
const ALL_SEARCHES = ''

export const ContentAutopilotKeywordModifiers = (): JSX.Element => {
    const { modifiers, modifiersLoading, modifiersError, modifierKeyword, keywords, filters } =
        useValues(contentAutopilotKeywordsLogic)
    const { loadModifiers, setModifierKeyword } = useActions(contentAutopilotKeywordsLogic)
    const options = [
        { value: ALL_SEARCHES, label: 'All searches' },
        ...(keywords ?? []).map((keyword) => ({
            value: keyword.keyword,
            label: `Searches with "${keyword.keyword}"`,
        })),
    ]

    return (
        <AiVisibilityCard
            title="What the engines add to your searches"
            description='Words the engines add to their searches, such as a year or "vs". A gap is a word whose answers cite you much less than usual.'
            actions={
                <Select<string>
                    value={modifierKeyword ?? ALL_SEARCHES}
                    onValueChange={(value) => setModifierKeyword(value || null)}
                >
                    <SelectTrigger
                        aria-label="Keyword filter"
                        className="max-w-full min-w-0"
                        data-attr="content-autopilot-keywords-modifier-filter"
                    >
                        <SelectValue className="truncate">
                            {(value: string | null) => options.find((option) => option.value === value)?.label}
                        </SelectValue>
                    </SelectTrigger>
                    <SelectContent>
                        {options.map((option) => (
                            <SelectItem key={option.value} value={option.value}>
                                {option.label}
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            }
        >
            <div className="flex flex-col gap-3" data-attr="content-autopilot-keywords-modifiers">
                {modifiersError ? (
                    <AiVisibilityBanner
                        type="error"
                        action={{ children: 'Try again', onClick: loadModifiers, loading: modifiersLoading }}
                    >
                        Couldn't load the search words. Try again, and if it keeps happening contact support.
                    </AiVisibilityBanner>
                ) : !modifiers ? (
                    <Skeleton className="h-24 w-full" />
                ) : modifiers.modifiers.length === 0 ? (
                    <Text
                        size="xs"
                        variant="muted"
                        render={<p className="m-0" />}
                        data-attr="content-autopilot-keywords-modifiers-empty"
                    >
                        {modifiers.answers === 0
                            ? `No answers ${modifierKeyword ? `searched for "${modifierKeyword}" ` : ''}${windowRange(modifiers)}.`
                            : 'The engines searched only for words your prompts already contain. Only some engines report the searches they run.'}
                    </Text>
                ) : (
                    <AiVisibilityTable<ModifierGroup>
                        size="small"
                        dataSource={modifierGroups(modifiers.modifiers)}
                        rowKey="kind"
                        loading={modifiersLoading}
                        columns={[
                            {
                                title: 'Group',
                                key: 'label',
                                render: (_, group) => (
                                    <div>
                                        <div className="font-semibold">{group.label}</div>
                                        <div className="text-xs text-muted-foreground">{group.description}</div>
                                    </div>
                                ),
                            },
                            {
                                title: 'Words',
                                key: 'modifiers',
                                render: (_, group) => (
                                    <span className="text-muted-foreground">
                                        {group.modifiers
                                            .slice(0, 4)
                                            .map((modifier) => modifier.term)
                                            .join(', ')}
                                        {group.modifiers.length > 4 ? ` and ${group.modifiers.length - 4} more` : ''}
                                    </span>
                                ),
                            },
                            {
                                title: 'Gaps',
                                key: 'kind',
                                align: 'right',
                                tooltip: 'Words in the group whose answers cite you much less than usual.',
                                render: (_, group) => {
                                    const gaps = group.modifiers.filter((modifier) =>
                                        isCitationGap(modifier, modifiers.baseline_cited_rate)
                                    ).length
                                    return gaps ? (
                                        <AiVisibilityTag type="danger">{pluralize(gaps, 'gap')}</AiVisibilityTag>
                                    ) : (
                                        <span className="text-muted-foreground">-</span>
                                    )
                                },
                            },
                        ]}
                        expandable={{
                            noIndent: true,
                            expandedRowRender: (group) => (
                                <ContentAutopilotKeywordModifierTerms
                                    modifiers={group.modifiers}
                                    baselineCitedRate={modifiers.baseline_cited_rate}
                                    dateFrom={modifiers.window_from}
                                    dateTo={modifiers.window_to}
                                    branded={filters.branded}
                                />
                            ),
                        }}
                    />
                )}
            </div>
        </AiVisibilityCard>
    )
}
