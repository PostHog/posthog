import { LemonInput, LemonInputSelect, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import type { CustomInputRendererProps } from 'lib/components/CyclotronJob/customInputRenderers'

import { ScannerPicker } from '../ScannerPicker/ScannerPicker'

type ScanSetupType = 'monitor' | 'classifier' | 'scorer' | 'summarizer' | 'scanner'

// The shape the workflow step stores and sends; the backend reads it in parse_workflow_scan_setup.
interface ScanSetup {
    type: ScanSetupType
    prompt?: string
    tags?: string[]
    scale?: { min: number; max: number }
    scanner_id?: string | null
}

const SETUP_OPTIONS: { value: ScanSetupType; label: string; placeholder?: string }[] = [
    { value: 'monitor', label: 'Ask a question', placeholder: 'Did the user hit an error while checking out?' },
    { value: 'classifier', label: 'Categorize', placeholder: 'What was the user trying to do?' },
    { value: 'scorer', label: 'Score', placeholder: 'How frustrated was the user?' },
    { value: 'summarizer', label: 'Summarize', placeholder: 'Summarize what the user did and any problems they hit.' },
    { value: 'scanner', label: 'Use a saved scanner' },
]

const DEFAULT_SCALE = { min: 1, max: 5 }

export default function CyclotronJobInputReplayVisionScan({ value, onChange }: CustomInputRendererProps): JSX.Element {
    const setup: ScanSetup = value && typeof value === 'object' ? value : { type: 'monitor' }
    const option = SETUP_OPTIONS.find((candidate) => candidate.value === setup.type) ?? SETUP_OPTIONS[0]
    const update = (changes: Partial<ScanSetup>): void => onChange({ ...setup, ...changes })

    return (
        <div className="flex flex-col gap-2">
            <LemonSelect
                data-attr="replay-vision-scan-type"
                value={option.value}
                options={SETUP_OPTIONS.map(({ value, label }) => ({ value, label }))}
                onChange={(type) =>
                    update({ type, ...(type === 'scorer' && !setup.scale ? { scale: DEFAULT_SCALE } : {}) })
                }
                fullWidth
            />
            {option.value === 'scanner' ? (
                <ScannerPicker
                    value={setup.scanner_id ?? null}
                    onChange={(scannerId) => update({ scanner_id: scannerId })}
                />
            ) : (
                <LemonTextArea
                    data-attr="replay-vision-scan-prompt"
                    value={setup.prompt ?? ''}
                    onChange={(prompt) => update({ prompt })}
                    placeholder={option.placeholder}
                    minRows={2}
                />
            )}
            {option.value === 'classifier' && (
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    data-attr="replay-vision-scan-categories"
                    placeholder="Add the categories to choose from"
                    value={setup.tags ?? []}
                    onChange={(tags) => update({ tags })}
                />
            )}
            {option.value === 'scorer' && (
                <div className="flex items-center gap-2">
                    <span>From</span>
                    <LemonInput
                        type="number"
                        data-attr="replay-vision-scan-scale-min"
                        value={setup.scale?.min ?? DEFAULT_SCALE.min}
                        onChange={(min) => update({ scale: { ...(setup.scale ?? DEFAULT_SCALE), min: min ?? 0 } })}
                        className="w-20"
                    />
                    <span>to</span>
                    <LemonInput
                        type="number"
                        data-attr="replay-vision-scan-scale-max"
                        value={setup.scale?.max ?? DEFAULT_SCALE.max}
                        onChange={(max) => update({ scale: { ...(setup.scale ?? DEFAULT_SCALE), max: max ?? 0 } })}
                        className="w-20"
                    />
                </div>
            )}
        </div>
    )
}
