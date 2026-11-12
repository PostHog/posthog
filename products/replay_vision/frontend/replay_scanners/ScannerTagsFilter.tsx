import { IconChevronDown } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TagSelect } from 'lib/components/TagSelect'
import { useTagSourceExcluding } from 'lib/components/useTagPages'

import { isUnusableScannerTag } from './scannerTags'

export function ScannerTagsFilter({
    value,
    onChange,
}: {
    value: string[]
    onChange: (tags: string[]) => void
}): JSX.Element {
    const loadTags = useTagSourceExcluding(isUnusableScannerTag)

    return (
        <TagSelect
            value={value}
            onChange={onChange}
            loadTags={loadTags}
            logicKey="vision-scanners-tags-filter"
            listDataAttr="vision-scanners-tags-filter-list"
        >
            {(selected) => (
                <LemonButton
                    type="secondary"
                    size="small"
                    sideIcon={<IconChevronDown />}
                    data-attr="vision-scanners-tags-filter"
                >
                    {selected.length > 0 ? `Tags (${selected.length})` : 'Tags'}
                </LemonButton>
            )}
        </TagSelect>
    )
}
