import { LemonInput, LemonSegmentedButton, LemonSwitch, LemonTextArea } from '@posthog/lemon-ui'

import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'

import { LensConfig, ReplayLens, SummarizerLensConfig } from '../types'

interface Props {
    lens: ReplayLens
    onChange: (config: LensConfig) => void
}

const SUMMARIZER_LENGTH_OPTIONS: { value: SummarizerLensConfig['length']; label: string }[] = [
    { value: 'short', label: 'Short (1-2 sentences)' },
    { value: 'medium', label: 'Medium (1 paragraph)' },
    { value: 'long', label: 'Long (3-5 paragraphs)' },
]

export function LensTypeConfigEditor({ lens, onChange }: Props): JSX.Element {
    if (lens.lens_type === 'summarizer') {
        const config = lens.lens_config
        return (
            <div className="space-y-4">
                <PromptField
                    value={config.prompt}
                    onChange={(prompt) => onChange({ ...config, prompt })}
                    placeholder="Summarize what the user did, focusing on their goal and any obstacles they hit."
                    helper="The model will produce a title and a body of text following this prompt."
                />
                <div className="space-y-2">
                    <label className="block text-sm font-medium">Summary length</label>
                    <LemonSegmentedButton
                        value={config.length}
                        onChange={(value) => onChange({ ...config, length: value as SummarizerLensConfig['length'] })}
                        options={SUMMARIZER_LENGTH_OPTIONS}
                    />
                </div>
            </div>
        )
    }

    if (lens.lens_type === 'monitor') {
        const config = lens.lens_config
        return (
            <PromptField
                value={config.prompt}
                onChange={(prompt) => onChange({ ...config, prompt })}
                placeholder="Did the user encounter a payment failure? Answer yes or no with a one-sentence reason."
                helper="The model will return a yes/no verdict with a short reasoning string."
            />
        )
    }

    if (lens.lens_type === 'classifier') {
        const config = lens.lens_config
        return (
            <div className="space-y-4">
                <PromptField
                    value={config.prompt}
                    onChange={(prompt) => onChange({ ...config, prompt })}
                    placeholder="Categorize this session by its primary user intent."
                    helper="The model will pick one or more tags from the vocabulary you define below."
                />
                <div className="space-y-2">
                    <label className="block text-sm font-medium">Tag vocabulary</label>
                    <LemonInputSelect
                        mode="multiple"
                        allowCustomValues
                        placeholder="Type a tag and press enter..."
                        value={config.tags}
                        onChange={(tags) => onChange({ ...config, tags })}
                        options={config.tags.map((t) => ({ key: t, label: t }))}
                    />
                    <p className="text-xs text-muted">
                        The model is constrained to picking from this list. Add the tags you want to discriminate
                        between.
                    </p>
                </div>
                <div className="flex items-center gap-2">
                    <LemonSwitch
                        checked={config.multi_label}
                        onChange={(multi_label) => onChange({ ...config, multi_label })}
                    />
                    <div>
                        <div className="text-sm font-medium">Allow multiple tags per session</div>
                        <div className="text-xs text-muted">
                            When off, the model picks exactly one tag. When on, it can pick zero or more.
                        </div>
                    </div>
                </div>
            </div>
        )
    }

    if (lens.lens_type === 'scorer') {
        const config = lens.lens_config
        return (
            <div className="space-y-4">
                <PromptField
                    value={config.prompt}
                    onChange={(prompt) => onChange({ ...config, prompt })}
                    placeholder="Rate how frustrated the user appeared during this session."
                    helper="The model will return a single number on the scale below plus a short reasoning string."
                />
                <div className="space-y-2">
                    <label className="block text-sm font-medium">Scale</label>
                    <div className="flex items-center gap-3 max-w-md">
                        <LemonInput
                            type="number"
                            value={config.scale.min}
                            onChange={(v) => onChange({ ...config, scale: { ...config.scale, min: Number(v) || 0 } })}
                            prefix={<span className="text-muted text-xs">min</span>}
                        />
                        <span className="text-muted">to</span>
                        <LemonInput
                            type="number"
                            value={config.scale.max}
                            onChange={(v) => onChange({ ...config, scale: { ...config.scale, max: Number(v) || 0 } })}
                            prefix={<span className="text-muted text-xs">max</span>}
                        />
                    </div>
                </div>
                <div className="space-y-2">
                    <label className="block text-sm font-medium">Score label (optional)</label>
                    <LemonInput
                        value={config.scale.label ?? ''}
                        onChange={(v) => onChange({ ...config, scale: { ...config.scale, label: v || undefined } })}
                        placeholder="frustration"
                    />
                    <p className="text-xs text-muted">
                        A short label describing what the score represents. Stamped on each observation.
                    </p>
                </div>
            </div>
        )
    }

    if (lens.lens_type === 'indexer') {
        const config = lens.lens_config
        return (
            <PromptField
                value={config.prompt}
                onChange={(prompt) => onChange({ ...config, prompt })}
                placeholder="Focus on the user's actions and goals. Ignore loading screens and animation noise."
                helper="The model produces semantic embeddings of the session so it becomes findable via free-text search."
            />
        )
    }

    return <div className="text-muted text-sm">Unsupported lens type.</div>
}

interface PromptFieldProps {
    value: string
    onChange: (value: string) => void
    placeholder: string
    helper: string
}

function PromptField({ value, onChange, placeholder, helper }: PromptFieldProps): JSX.Element {
    return (
        <div className="space-y-2">
            <label className="block text-sm font-medium">
                Prompt <span className="text-danger">*</span>
            </label>
            <LemonTextArea value={value} onChange={onChange} placeholder={placeholder} minRows={6} />
            <div className="text-xs text-muted">{helper}</div>
        </div>
    )
}
