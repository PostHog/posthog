import { useValues } from 'kea'
import { Field } from 'kea-forms'

import { LemonInput, LemonSegmentedButton, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { replayScannerLogic } from '../replayScannerLogic'
import { SummarizerScannerConfig } from '../types'

const SUMMARIZER_LENGTH_OPTIONS: { value: SummarizerScannerConfig['length']; label: string }[] = [
    { value: 'short', label: 'Short (1-2 sentences)' },
    { value: 'medium', label: 'Medium (1 paragraph)' },
    { value: 'long', label: 'Long (3-5 paragraphs)' },
]

export function ScannerTypeConfigEditor({ scannerId, tabId }: { scannerId: string; tabId: string }): JSX.Element {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId, tabId }))

    if (!scanner) {
        return <div className="text-muted">Loading…</div>
    }

    if (scanner.scanner_type === 'summarizer') {
        return (
            <div className="space-y-4">
                <Field name="scanner_config.prompt" label="Prompt">
                    <LemonTextArea
                        placeholder="Summarize what the user did, focusing on their goal and any obstacles they hit."
                        minRows={6}
                    />
                </Field>
                <Field name="scanner_config.length" label="Summary length">
                    <LemonSegmentedButton options={SUMMARIZER_LENGTH_OPTIONS} />
                </Field>
            </div>
        )
    }

    if (scanner.scanner_type === 'monitor') {
        return (
            <Field name="scanner_config.prompt" label="Prompt">
                <LemonTextArea
                    placeholder="Did the user encounter a payment failure? Answer yes or no with a one-sentence reason."
                    minRows={6}
                />
            </Field>
        )
    }

    if (scanner.scanner_type === 'classifier') {
        return (
            <div className="space-y-4">
                <Field name="scanner_config.prompt" label="Prompt">
                    <LemonTextArea placeholder="Categorize this session by its primary user intent." minRows={6} />
                </Field>
                <Field name="scanner_config.tags" label="Tag vocabulary">
                    {({ value, onChange }) => (
                        <LemonInputSelect
                            mode="multiple"
                            allowCustomValues
                            placeholder="Type a tag and press enter..."
                            value={(value as string[]) ?? []}
                            onChange={onChange}
                            options={((value as string[]) ?? []).map((t) => ({ key: t, label: t }))}
                        />
                    )}
                </Field>
                <Field name="scanner_config.multi_label">
                    {({ value, onChange }) => (
                        <div className="flex items-center gap-2">
                            <LemonSwitch checked={!!value} onChange={onChange} />
                            <div>
                                <div className="text-sm font-medium">Allow multiple tags per session</div>
                                <div className="text-xs text-muted">
                                    When off, the model picks exactly one tag. When on, it can pick zero or more.
                                </div>
                            </div>
                        </div>
                    )}
                </Field>
            </div>
        )
    }

    if (scanner.scanner_type === 'scorer') {
        return (
            <div className="space-y-4">
                <Field name="scanner_config.prompt" label="Prompt">
                    <LemonTextArea
                        placeholder="Rate how frustrated the user appeared during this session."
                        minRows={6}
                    />
                </Field>
                <Field name="scanner_config.scale">
                    {({ value, onChange, error }) => {
                        const scale = (value as { min: number; max: number; label?: string }) ?? { min: 0, max: 10 }
                        return (
                            <div className="space-y-3">
                                <div className="space-y-1">
                                    <label className="block text-sm font-medium">Scale</label>
                                    <div className="flex items-center gap-3 max-w-md">
                                        <LemonInput
                                            type="number"
                                            value={scale.min}
                                            onChange={(v) => onChange({ ...scale, min: Number(v) || 0 })}
                                            prefix={<span className="text-muted text-xs">min</span>}
                                        />
                                        <span className="text-muted">to</span>
                                        <LemonInput
                                            type="number"
                                            value={scale.max}
                                            onChange={(v) => onChange({ ...scale, max: Number(v) || 0 })}
                                            prefix={<span className="text-muted text-xs">max</span>}
                                        />
                                    </div>
                                    {error && <div className="text-xs text-danger">{error}</div>}
                                </div>
                                <div className="space-y-1">
                                    <label className="block text-sm font-medium">Score label (optional)</label>
                                    <LemonInput
                                        value={scale.label ?? ''}
                                        onChange={(v) => onChange({ ...scale, label: v || undefined })}
                                        placeholder="frustration"
                                    />
                                </div>
                            </div>
                        )
                    }}
                </Field>
            </div>
        )
    }

    if (scanner.scanner_type === 'indexer') {
        return (
            <Field name="scanner_config.prompt" label="Prompt">
                <LemonTextArea
                    placeholder="Focus on the user's actions and goals. Ignore loading screens and animation noise."
                    minRows={6}
                />
            </Field>
        )
    }

    return <div className="text-muted text-sm">Unsupported scanner type.</div>
}
