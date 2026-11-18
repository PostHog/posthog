import { useActions, useValues } from 'kea'

import { IconList } from '@posthog/icons'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuSeparator,
    FilterCheckboxSubMenu,
    FilterClearItem,
    FilterMenuTrigger,
    FilterOption,
    FilterRadioSubMenu,
    FilterSearchSubMenu,
} from '@posthog/quill'

import { QuillPersonAvatar } from 'lib/components/QuillPersonAvatar/QuillPersonAvatar'
import { fullName } from 'lib/utils/strings'
import { userLogic } from 'scenes/userLogic'

import { membersLogic } from '~/models/membersLogic'

import { RELEASE_ALL_TYPES, ReleaseAllOrder, ReleaseAllType, releaseAllLogic } from './releaseAllLogic'
import { RELEASE_ALL_TYPE_INFO } from './releaseAllTypeInfo'

const SORT_OPTIONS: FilterOption<ReleaseAllOrder>[] = [
    { value: '-created_at', label: 'Newest first' },
    { value: 'created_at', label: 'Oldest first' },
]

const TYPE_OPTIONS: FilterOption<ReleaseAllType>[] = RELEASE_ALL_TYPES.map((type) => ({
    value: type,
    label: RELEASE_ALL_TYPE_INFO[type].pluralLabel,
    icon: (
        // eslint-disable-next-line react/forbid-dom-props
        <span className="flex items-center" style={{ color: RELEASE_ALL_TYPE_INFO[type].color }}>
            {RELEASE_ALL_TYPE_INFO[type].icon}
        </span>
    ),
}))

export function ReleaseAllFilterMenu(): JSX.Element {
    const { filters, narrowingFiltersActive } = useValues(releaseAllLogic)
    const { setFilters, clearNarrowingFilters } = useActions(releaseAllLogic)
    const { meFirstMembers, membersLoading } = useValues(membersLogic)
    const { ensureAllMembersLoaded } = useActions(membersLogic)
    const { user } = useValues(userLogic)

    return (
        <DropdownMenu onOpenChange={(open) => open && filters.owners.length > 0 && ensureAllMembersLoaded()}>
            <FilterMenuTrigger active={narrowingFiltersActive} dataAttr="release-all-filter" />
            <DropdownMenuContent align="start" className="min-w-64">
                <FilterRadioSubMenu
                    label="Sort by"
                    options={SORT_OPTIONS}
                    value={filters.order}
                    onChange={(order) => setFilters({ order })}
                    optionDataAttr="release-all-sort"
                />
                <DropdownMenuSeparator />
                <FilterCheckboxSubMenu
                    label="Type"
                    allLabel="All types"
                    allIcon={<IconList />}
                    pluralNoun="types"
                    options={TYPE_OPTIONS}
                    selected={filters.types}
                    onChange={(types) => setFilters({ types })}
                    dataAttr="release-all-type-picker"
                    optionDataAttr="release-all-type-filter"
                />
                <FilterSearchSubMenu
                    label="Owner"
                    allLabel="Anyone"
                    pluralNoun="people"
                    options={meFirstMembers.map((member) => ({
                        value: String(member.user.id),
                        label: fullName(member.user) || member.user.email,
                        icon: (
                            <QuillPersonAvatar
                                name={member.user.first_name || member.user.email}
                                email={member.user.email}
                                size="xs"
                            />
                        ),
                        hint: member.user.uuid === user?.uuid ? '(you)' : undefined,
                    }))}
                    selected={filters.owners.map(String)}
                    onChange={(owners) => setFilters({ owners: owners.map(Number) })}
                    loading={membersLoading}
                    searchPlaceholder="Search people"
                    emptyText="No one matches"
                    onOpen={ensureAllMembersLoaded}
                    dataAttr="release-all-owner"
                    optionDataAttr="release-all-owner-option"
                />
                <FilterClearItem
                    active={narrowingFiltersActive}
                    onClear={clearNarrowingFilters}
                    dataAttr="release-all-clear"
                />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
