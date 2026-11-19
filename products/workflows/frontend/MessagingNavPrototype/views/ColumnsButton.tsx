// PROTOTYPE, never merged: PostHog/michaelr-context#421. Picks the columns a view shows.
import { IconCheck, IconColumns } from '@posthog/icons'
import { LemonButton, LemonMenu } from '@posthog/lemon-ui'

import { COLUMN_LABELS, ColumnKey, ViewQuery } from './viewsPrototypeStore'

const COLUMNS_BY_TYPE: Record<string, ColumnKey[]> = {
    broadcast: ['when', 'recipients'],
    transactional: ['slug', 'sent7d'],
    workflow: ['trigger', 'channels'],
}

export function ColumnsButton({
    query,
    onChange,
    iconOnly,
}: {
    query: ViewQuery
    onChange: (columns: ColumnKey[]) => void
    iconOnly?: boolean
}): JSX.Element {
    const available: ColumnKey[] = [
        'name',
        ...(query.types.length > 1 ? (['type'] as ColumnKey[]) : []),
        'status',
        'tags',
        ...query.types.flatMap((type) => COLUMNS_BY_TYPE[type]),
        'createdBy',
        'updated',
    ]
    return (
        <LemonMenu
            closeOnClickInside={false}
            items={available.map((key) => ({
                label: COLUMN_LABELS[key],
                icon: query.columns.includes(key) ? <IconCheck /> : <span className="size-4" />,
                disabledReason: key === 'name' ? 'Every view shows the name' : undefined,
                onClick: () =>
                    onChange(
                        query.columns.includes(key)
                            ? query.columns.filter((c) => c !== key)
                            : available.filter((c) => c === key || query.columns.includes(c))
                    ),
            }))}
        >
            <LemonButton
                size="small"
                type="secondary"
                icon={<IconColumns />}
                tooltip={iconOnly ? 'Columns' : undefined}
                data-attr="messaging-prototype-columns"
            >
                {iconOnly ? undefined : 'Columns'}
            </LemonButton>
        </LemonMenu>
    )
}
