import { useValues } from 'kea'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { scannerPickerLogic } from './scannerPickerLogic'

export default function CyclotronJobInputScannerPicker({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const { scanners, scannersLoading } = useValues(scannerPickerLogic)

    const selected = typeof value === 'string' ? value : ''
    const options: LemonInputSelectOption[] = scanners.map((scanner) => ({
        key: scanner.id,
        label: scanner.enabled === false ? `${scanner.name} (paused)` : scanner.name,
    }))
    // A stored id that isn't among this team's scanners (deleted since, or authored elsewhere)
    // still renders as itself, not as blank.
    if (selected && !options.some((option) => option.key === selected)) {
        options.push({ key: selected, label: selected })
    }

    return (
        <LemonInputSelect
            mode="single"
            data-attr="select-replay-vision-scanner"
            placeholder={scannersLoading ? 'Loading scanners...' : 'Select a scanner...'}
            value={selected ? [selected] : []}
            onChange={(val) => onChange(val[0] ?? null)}
            options={options}
            loading={scannersLoading}
        />
    )
}
