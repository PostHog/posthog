import { TagSelect } from 'lib/components/TagSelect'

import type { ScoutTagOption } from '../../../utils/scoutTags'

export function ScoutTagsFilter({
    options,
    selected,
    onChange,
    size = 'small',
}: {
    options: ScoutTagOption[]
    selected: string[]
    onChange: (tags: string[]) => void
    size?: 'xsmall' | 'small'
}): JSX.Element {
    return (
        <TagSelect
            options={options}
            value={selected}
            defaultLabel="Any tag"
            size={size}
            aria-label="Filter scouts by tag"
            onChange={onChange}
        />
    )
}
