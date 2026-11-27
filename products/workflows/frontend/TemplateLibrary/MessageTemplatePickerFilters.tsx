import { useActions, useValues } from 'kea'

import { MemberSelect } from 'lib/components/MemberSelect'
import { TagSelect } from 'lib/components/TagSelect'
import { LemonInput } from 'lib/lemon-ui/LemonInput/LemonInput'

import { messageTemplatesLogic } from './messageTemplatesLogic'

export function MessageTemplatePickerFilters(): JSX.Element {
    const logic = messageTemplatesLogic({ listKey: 'template-picker' })
    const { search, createdByFilter, tagsFilter } = useValues(logic)
    const { setSearch, setCreatedByFilter, setTagsFilter } = useActions(logic)

    return (
        <div className="flex flex-wrap gap-2 items-center">
            <LemonInput
                type="search"
                placeholder="Search templates"
                value={search}
                onChange={setSearch}
                className="flex-1 min-w-48"
                autoFocus
                data-attr="template-picker-search"
            />
            <MemberSelect
                defaultLabel="Any creator"
                value={createdByFilter}
                onChange={(user) => setCreatedByFilter(user?.id ?? null)}
            />
            <TagSelect
                size="small"
                defaultLabel="Any tags"
                value={tagsFilter}
                onChange={setTagsFilter}
                listDataAttr="template-picker-tags-filter-list"
            />
        </div>
    )
}
