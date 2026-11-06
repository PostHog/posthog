import { useValues } from 'kea'

import { LemonInputSelect, LemonInputSelectOption } from '@posthog/lemon-ui'

import { scannerPickerLogic } from './scannerPickerLogic'

export interface ScannerPickerProps {
    value: string | null
    onChange: (scannerId: string | null) => void
}

export function ScannerPicker({ value, onChange }: ScannerPickerProps): JSX.Element {
    const { scanners, scannersLoading } = useValues(scannerPickerLogic)

    const options: LemonInputSelectOption[] = scanners.map((scanner) => ({
        key: scanner.id,
        label: scanner.enabled === false ? `${scanner.name} (paused)` : scanner.name,
    }))
    // A stored id that isn't among this team's scanners (deleted since, or authored elsewhere)
    // still renders as itself, not as blank.
    if (value && !options.some((option) => option.key === value)) {
        options.push({ key: value, label: value })
    }

    return (
        <LemonInputSelect
            mode="single"
            data-attr="select-replay-vision-scanner"
            placeholder={scannersLoading ? 'Loading scanners...' : 'Select a scanner...'}
            value={value ? [value] : []}
            onChange={(val) => onChange(val[0] ?? null)}
            options={options}
            loading={scannersLoading}
        />
    )
}
