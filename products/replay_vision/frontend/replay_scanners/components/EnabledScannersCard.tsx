import { useValues } from 'kea'

import { cn } from 'lib/utils/css-classes'

import { ScannerTypeBadge } from '../../components/ScannerTypeBadge'
import { replayScannersLogic } from '../replayScannersLogic'
import { SCANNER_TYPE_OPTIONS } from '../types'

export function EnabledScannersCard({ className }: { className?: string }): JSX.Element {
    const { scannerStats } = useValues(replayScannersLogic)

    return (
        <div className={cn('bg-bg-light border rounded p-4 flex flex-col', className)}>
            <div className="text-muted text-xs font-medium uppercase mb-2">Enabled scanners</div>
            <div className="text-3xl font-semibold">
                {scannerStats?.enabled ?? 0}
                <span className="text-muted text-lg font-normal">
                    {' / '}
                    {scannerStats?.total ?? 0}
                </span>
            </div>
            <div className="flex flex-wrap gap-1.5 mt-3">
                {SCANNER_TYPE_OPTIONS.map(({ value }) => {
                    const { enabled = 0, total = 0 } = scannerStats?.by_type?.[value] ?? {}
                    return (
                        <ScannerTypeBadge
                            key={value}
                            scannerType={value}
                            variant={total > 0 ? 'default' : 'muted'}
                            suffix={`${enabled}/${total}`}
                        />
                    )
                })}
            </div>
        </div>
    )
}
