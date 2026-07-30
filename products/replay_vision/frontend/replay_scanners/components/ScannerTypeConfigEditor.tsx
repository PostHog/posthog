import { useActions, useValues } from 'kea'
import { useCallback } from 'react'

import { IconAI, IconPlus, IconX } from '@posthog/icons'
import {
    LemonButton,
    LemonCard,
    LemonInput,
    LemonSegmentedButton,
    LemonSwitch,
    LemonTag,
    LemonTextArea,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInputSelect } from 'lib/lemon-ui/LemonInputSelect/LemonInputSelect'
import { useMaxTool } from 'scenes/max/useMaxTool'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { replayScannerLogic } from '../replayScannerLogic'
import { ClassifierScannerConfig, SummarizerScannerConfig, scannerTypeLabel } from '../types'

const SUMMARIZER_LENGTH_OPTIONS: { value: SummarizerScannerConfig['length']; label: string }[] = [
    { value: 'short', label: 'Short (1-2 sentences)' },
    { value: 'medium', label: 'Medium (1 paragraph)' },
    { value: 'long', label: 'Long (3-5 paragraphs)' },
]

/** Prompt field with a Max entry point that drafts the prompt and fills it back into the form. */
function ScannerPromptField({
    scannerId,
    placeholder,
    label = 'Prompt',
    caption,
}: {
    scannerId: string
    placeholder: string
    label?: string
    caption?: string
}): JSX.Element {
    const logic = replayScannerLogic({ id: scannerId })
    const { scanner } = useValues(logic)
    const { setScannerValue } = useActions(logic)

    const onDraftedPrompt = useCallback(
        (toolOutput: { prompt?: string; error?: string }) => {
            if (!toolOutput?.error && toolOutput?.prompt) {
                setScannerValue(['scanner_config', 'prompt'], toolOutput.prompt)
            }
        },
        [setScannerValue]
    )

    const { openMax } = useMaxTool({
        identifier: 'draft_replay_vision_scanner_prompt',
        active: !!scanner,
        context: {
            scanner_type: scanner?.scanner_type,
            current_prompt: scanner?.scanner_config?.prompt || '',
        },
        contextDescription: scanner
            ? { text: `${scannerTypeLabel(scanner.scanner_type)} scanner`, icon: iconForType('session_replay') }
            : undefined,
        initialMaxPrompt: 'Help me write the prompt for this scanner',
        callback: onDraftedPrompt,
    })

    useAttachedContext(
        scanner
            ? [
                  { type: 'replay_vision_scanner', key: scannerId, label: scannerTypeLabel(scanner?.scanner_type) },
                  {
                      type: 'replay_vision_scanner_prompt',
                      value: JSON.stringify(scanner?.scanner_config?.prompt || ''),
                      label: 'Current prompt',
                  },
              ]
            : null,
        { active: !!scanner }
    )

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
                <label className="text-sm font-medium">{label}</label>
                {openMax && (
                    <LemonButton
                        size="xsmall"
                        type="secondary"
                        icon={<IconAI />}
                        onClick={() => openMax()}
                        data-attr="replay-vision-write-prompt-with-ai"
                    >
                        Write with PostHog AI
                    </LemonButton>
                )}
            </div>
            <LemonField name="scanner_config.prompt">
                <LemonTextArea placeholder={placeholder} minRows={6} />
            </LemonField>
            {caption && <div className="text-xs text-muted">{caption}</div>}
        </div>
    )
}

const SUGGESTION_SOURCE_META: Record<string, { label: string; type: 'success' | 'primary' | 'default' }> = {
    observed: { label: 'Seen in recordings', type: 'success' },
    product: { label: 'From your product', type: 'primary' },
    prompt: { label: 'From the goal', type: 'default' },
}

/** Grounded tag suggestions, each shown with the evidence it came from and a one-click add. */
function ClassifierTagSuggestions({ scannerId }: { scannerId: string }): JSX.Element | null {
    const logic = replayScannerLogic({ id: scannerId })
    const { tagSuggestions } = useValues(logic)
    const { acceptTagSuggestion, acceptAllTagSuggestions, dismissTagSuggestions } = useActions(logic)

    if (tagSuggestions.length === 0) {
        return null
    }
    return (
        <LemonCard className="space-y-2">
            <div className="flex items-center justify-between">
                <span className="text-sm font-medium">Suggested tags</span>
                <div className="flex items-center gap-1">
                    <LemonButton size="xsmall" type="secondary" onClick={() => acceptAllTagSuggestions()}>
                        Add all
                    </LemonButton>
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        tooltip="Dismiss"
                        onClick={() => dismissTagSuggestions()}
                    />
                </div>
            </div>
            <div className="space-y-2">
                {tagSuggestions.map((suggestion) => {
                    const meta = SUGGESTION_SOURCE_META[suggestion.source] ?? SUGGESTION_SOURCE_META.prompt
                    return (
                        <div key={suggestion.tag} className="flex items-start gap-2">
                            <LemonButton
                                size="xsmall"
                                type="secondary"
                                icon={<IconPlus />}
                                tooltip="Add to vocabulary"
                                onClick={() => acceptTagSuggestion(suggestion.tag)}
                            />
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-1.5">
                                    <span className="font-mono text-xs">{suggestion.tag}</span>
                                    <LemonTag size="small" type={meta.type}>
                                        {meta.label}
                                    </LemonTag>
                                </div>
                                <div className="text-xs text-muted">{suggestion.rationale}</div>
                            </div>
                        </div>
                    )
                })}
            </div>
        </LemonCard>
    )
}

/** Tag-vocabulary field with an AI entry point that suggests grounded tags to add. */
function ClassifierTagsField({ scannerId }: { scannerId: string }): JSX.Element {
    const logic = replayScannerLogic({ id: scannerId })
    const { scanner, tagSuggestionsLoading } = useValues(logic)
    const { loadTagSuggestions } = useActions(logic)

    const config = scanner?.scanner_config as ClassifierScannerConfig | undefined
    const hasPrompt = !!config?.prompt?.trim()

    return (
        <div className="space-y-2">
            <LemonField
                name="scanner_config.tags"
                label={
                    <span className="flex w-full items-center justify-between gap-2">
                        Tag vocabulary
                        <LemonButton
                            size="xsmall"
                            type="secondary"
                            icon={<IconAI />}
                            loading={tagSuggestionsLoading}
                            disabledReason={hasPrompt ? undefined : 'Add a prompt first so suggestions match your goal'}
                            onClick={() => loadTagSuggestions()}
                            data-attr="replay-vision-suggest-tags-with-ai"
                        >
                            Suggest tags with PostHog AI
                        </LemonButton>
                    </span>
                }
            >
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
            </LemonField>
            <ClassifierTagSuggestions scannerId={scannerId} />
        </div>
    )
}

export function ScannerTypeConfigEditor({ scannerId }: { scannerId: string }): JSX.Element {
    const { scanner } = useValues(replayScannerLogic({ id: scannerId }))

    if (!scanner) {
        return <div className="text-muted">Loading…</div>
    }

    if (scanner.scanner_type === 'summarizer') {
        return (
            <div className="space-y-4">
                <ScannerPromptField
                    scannerId={scannerId}
                    label="Additional context"
                    caption="The core summarizer prompt is built in. Use this field to add product context or steer summaries — for example, what the ideal user flow looks like."
                    placeholder="e.g. This is a B2B analytics tool. Users usually come to build a dashboard — call out where they get stuck in that flow."
                />
                <LemonField name="scanner_config.length" label="Summary length">
                    <LemonSegmentedButton options={SUMMARIZER_LENGTH_OPTIONS} />
                </LemonField>
            </div>
        )
    }

    if (scanner.scanner_type === 'monitor') {
        return (
            <div className="space-y-4">
                <ScannerPromptField
                    scannerId={scannerId}
                    placeholder="Did the user encounter a payment failure? Answer yes or no with a one-sentence reason."
                />
                <LemonField name="scanner_config.allow_inconclusive">
                    {({ value, onChange }) => (
                        <div className="flex items-center gap-2">
                            <LemonSwitch checked={!!value} onChange={onChange} />
                            <div>
                                <div className="text-sm font-medium">Allow inconclusive verdicts</div>
                                <div className="text-xs text-muted">
                                    Lets the model answer inconclusive when the recording doesn't contain enough
                                    evidence to decide. Otherwise it must commit to yes or no.
                                </div>
                            </div>
                        </div>
                    )}
                </LemonField>
            </div>
        )
    }

    if (scanner.scanner_type === 'classifier') {
        return (
            <div className="space-y-4">
                <ScannerPromptField
                    scannerId={scannerId}
                    placeholder="Categorize this session by its primary user intent."
                />
                <ClassifierTagsField scannerId={scannerId} />
                <LemonField name="scanner_config.multi_label">
                    {({ value, onChange }) => (
                        <div className="flex items-center gap-2">
                            <LemonSwitch checked={!!value} onChange={onChange} />
                            <div>
                                <div className="text-sm font-medium">Allow multiple tags per session</div>
                                <div className="text-xs text-muted">
                                    Otherwise the model picks exactly one tag from your vocabulary.
                                </div>
                            </div>
                        </div>
                    )}
                </LemonField>
                <LemonField name="scanner_config.allow_freeform_tags">
                    {({ value, onChange }) => (
                        <div className="flex items-center gap-2">
                            <LemonSwitch checked={!!value} onChange={onChange} />
                            <div>
                                <div className="text-sm font-medium">Allow freeform tags</div>
                                <div className="text-xs text-muted">
                                    Lets the model emit tags outside your tag vocabulary.
                                </div>
                            </div>
                        </div>
                    )}
                </LemonField>
            </div>
        )
    }

    if (scanner.scanner_type === 'scorer') {
        return (
            <div className="space-y-4">
                <ScannerPromptField
                    scannerId={scannerId}
                    placeholder="Rate how frustrated the user appeared during this session."
                />
                <LemonField name="scanner_config.scale">
                    {({ value, onChange, error }) => {
                        const scale = (value as { min: number; max: number; label?: string }) ?? { min: 0, max: 10 }
                        return (
                            <div className="space-y-3">
                                <div className="space-y-1">
                                    <label className="block text-sm font-medium">Scale</label>
                                    <div className="flex items-center gap-3 max-w-md">
                                        <LemonInput
                                            type="number"
                                            value={Number.isFinite(scale.min) ? scale.min : undefined}
                                            onChange={(v) => onChange({ ...scale, min: v ?? Number.NaN })}
                                            prefix={<span className="text-muted text-xs">min</span>}
                                        />
                                        <span className="text-muted">to</span>
                                        <LemonInput
                                            type="number"
                                            value={Number.isFinite(scale.max) ? scale.max : undefined}
                                            onChange={(v) => onChange({ ...scale, max: v ?? Number.NaN })}
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
                </LemonField>
            </div>
        )
    }

    return <div className="text-muted text-sm">Unsupported scanner type.</div>
}
