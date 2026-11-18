import { useMountedLogic } from 'kea'

import { LemonCollapse } from '@posthog/lemon-ui'

import { backfillsLogic } from '../backfillsLogic'
import { BackfillDateRange } from './BackfillDateRange'
import { BatchScanRecordings } from './BatchScanRecordings'
import { ScanSingleRecording } from './ScanSingleRecording'

type ScanMode = 'single' | 'batch' | 'backfill'

function PanelHeader({ title, hint }: { title: string; hint: string }): JSX.Element {
    return (
        <span className="flex flex-wrap items-baseline gap-x-2">
            <span className="font-semibold">{title}</span>
            <span className="text-xs text-muted font-normal">{hint}</span>
        </span>
    )
}

export function ScannerScanTab({ scannerId }: { scannerId: string }): JSX.Element {
    // Held for the whole tab, so reopening the backfill panel reuses the list and the default estimate.
    useMountedLogic(backfillsLogic({ scannerId }))
    return (
        <LemonCollapse<ScanMode>
            defaultActiveKey="single"
            panels={[
                {
                    key: 'single',
                    header: <PanelHeader title="Scan a single recording" hint="By session ID or link" />,
                    content: <ScanSingleRecording scannerId={scannerId} />,
                    dataAttr: 'vision-run-panel-single',
                },
                {
                    key: 'batch',
                    header: <PanelHeader title="Batch scan recordings" hint="Pick from a filtered list" />,
                    content: <BatchScanRecordings scannerId={scannerId} />,
                    dataAttr: 'vision-run-panel-batch',
                },
                {
                    key: 'backfill',
                    header: <PanelHeader title="Backfill a date range" hint="Every matching recording in a range" />,
                    content: <BackfillDateRange scannerId={scannerId} />,
                    dataAttr: 'vision-run-panel-backfill',
                },
            ]}
        />
    )
}
