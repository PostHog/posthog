import clsx from 'clsx'

import { LemonTable, LemonTableColumn, Tooltip } from '@posthog/lemon-ui'

import { percentage } from 'lib/utils/numbers'
import { pluralize } from 'lib/utils/strings'

import type { PromptConsensusCell, PromptConsensusMatrix } from './promptReport'
import { engineLabel } from './utils'

type ConsensusRow = PromptConsensusMatrix['rows'][number]

const heatClass = (share: number | null): string =>
    share === null || share === 0
        ? ''
        : share < 0.25
          ? 'bg-success/15'
          : share < 0.5
            ? 'bg-success/30'
            : share < 0.75
              ? 'bg-success/50'
              : 'bg-success/70'

const HeatCell = ({ cell, checks }: { cell: PromptConsensusCell; checks: number }): JSX.Element => (
    <Tooltip title={`${cell.checksCiting} of ${pluralize(checks, 'answer')} link to ${cell.domain}`}>
        <span className={clsx('block rounded px-2 py-1 text-right tabular-nums', heatClass(cell.share))}>
            {cell.share === null ? '-' : percentage(cell.share, 0)}
        </span>
    </Tooltip>
)

export const ContentAutopilotPromptConsensus = ({ matrix }: { matrix: PromptConsensusMatrix }): JSX.Element => {
    const columns: LemonTableColumn<ConsensusRow, keyof ConsensusRow | undefined>[] = [
        {
            title: 'Engine',
            key: 'engine',
            render: (_, row) => (
                <span className="whitespace-nowrap">
                    {engineLabel(row.engine)} <span className="text-muted">({pluralize(row.checks, 'answer')})</span>
                </span>
            ),
        },
        ...matrix.domains.map(
            (domain, index): LemonTableColumn<ConsensusRow, keyof ConsensusRow | undefined> => ({
                title: (
                    <Tooltip title={domain}>
                        <span className="block max-w-32 truncate">{domain}</span>
                    </Tooltip>
                ),
                key: domain,
                align: 'right',
                render: (_, row) => <HeatCell cell={row.cells[index]} checks={row.checks} />,
            })
        ),
    ]
    return (
        <div className="overflow-x-auto">
            <LemonTable
                size="small"
                dataSource={matrix.rows}
                rowKey="engine"
                columns={columns}
                emptyState="No answer in the last 30 days linked to a site."
            />
        </div>
    )
}
