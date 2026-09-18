import { IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonCheckbox, LemonMenu, LemonMenuItems } from '@posthog/lemon-ui'

import type { ScoutTagOption } from '../../../utils/scoutTags'

export function ScoutTagsFilter({
    options,
    selected,
    onToggle,
    onClear,
    size = 'small',
}: {
    options: ScoutTagOption[]
    selected: string[]
    onToggle: (tag: string) => void
    onClear: () => void
    size?: 'xsmall' | 'small'
}): JSX.Element {
    const label = selected.length === 0 ? 'Any tag' : selected.length === 1 ? selected[0] : `${selected.length} tags`
    const items: LemonMenuItems = [
        {
            title: 'Tagged',
            items: options.map((option) => ({
                icon: <LemonCheckbox checked={selected.includes(option.tag)} className="pointer-events-none" />,
                label: (
                    <span className="flex min-w-40 items-center justify-between gap-3">
                        <span className="truncate">{option.tag}</span>
                        <span className="text-muted tabular-nums">{option.count}</span>
                    </span>
                ),
                onClick: () => onToggle(option.tag),
            })),
            footer:
                selected.length > 0 ? (
                    <LemonButton type="tertiary" size="xsmall" fullWidth onClick={onClear}>
                        Clear tags
                    </LemonButton>
                ) : undefined,
        },
    ]

    return (
        <LemonMenu items={items} closeOnClickInside={false} placement="bottom-end">
            <LemonButton type="secondary" size={size} sideIcon={<IconChevronDown />} aria-label="Filter scouts by tag">
                {label}
            </LemonButton>
        </LemonMenu>
    )
}
