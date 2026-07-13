import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { LemonTag, LemonTagType } from 'lib/lemon-ui/LemonTag'

import type { AccountabilityStatusLineApi } from './generated/api.schemas'

function deltaTag(deltaPct: number | null): { label: string; type: LemonTagType } {
    if (deltaPct === null) {
        return { label: '—', type: 'default' }
    }
    const rounded = Math.round(deltaPct)
    if (rounded > 0) {
        return { label: `+${rounded}%`, type: 'success' }
    }
    if (rounded < 0) {
        return { label: `${rounded}%`, type: 'danger' }
    }
    return { label: '0%', type: 'default' }
}

export function AccountabilityPanel({ lines }: { lines: readonly AccountabilityStatusLineApi[] }): JSX.Element | null {
    if (lines.length === 0) {
        return null
    }

    const columns: LemonTableColumns<AccountabilityStatusLineApi> = [
        {
            title: 'Opportunity',
            key: 'title',
            render: (_, line) => <span className="font-semibold">{line.title}</span>,
        },
        { title: 'Then', key: 'baseline', render: (_, line) => line.baseline_summary },
        { title: 'Now', key: 'current', render: (_, line) => line.current_summary },
        {
            title: 'Change',
            key: 'delta',
            width: 0,
            render: (_, line) => {
                const { label, type } = deltaTag(line.delta_pct)
                return <LemonTag type={type}>{label}</LemonTag>
            },
        },
    ]

    return (
        <div className="flex flex-col gap-2">
            <div>
                <h3 className="mb-0">How past suggestions are doing</h3>
                <p className="text-muted mb-0">
                    Metrics re-measured against when each was suggested — movement, not attribution.
                </p>
            </div>
            <LemonTable dataSource={lines as AccountabilityStatusLineApi[]} columns={columns} rowKey="opportunity_id" />
        </div>
    )
}
