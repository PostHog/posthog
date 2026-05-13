import { LemonButton, LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { STEP_TYPES, SyntheticTestStep, SyntheticTestStepType } from '../../types'

interface StepBuilderProps {
    steps: SyntheticTestStep[]
    onChange: (steps: SyntheticTestStep[]) => void
}

const FIELDS_BY_TYPE: Record<SyntheticTestStepType, ('url' | 'selector' | 'value' | 'duration_ms')[]> = {
    navigate: ['url'],
    click: ['selector'],
    type: ['selector', 'value'],
    wait: ['duration_ms'],
    wait_for_selector: ['selector'],
    assert_element_exists: ['selector'],
    assert_url_contains: ['value'],
    assert_text_visible: ['value'],
}

const FIELD_PLACEHOLDERS: Record<string, string> = {
    url: 'https://us.posthog.com/signup',
    selector: '[data-attr=signup-submit]',
    value: 'Welcome',
    duration_ms: '1000',
}

export function StepBuilder({ steps, onChange }: StepBuilderProps): JSX.Element {
    const updateStep = (index: number, patch: Partial<SyntheticTestStep>): void => {
        const next = steps.map((s, i) => (i === index ? { ...s, ...patch } : s))
        onChange(next)
    }

    const removeStep = (index: number): void => {
        onChange(steps.filter((_, i) => i !== index))
    }

    const moveStep = (index: number, direction: -1 | 1): void => {
        const target = index + direction
        if (target < 0 || target >= steps.length) {
            return
        }
        const next = [...steps]
        ;[next[index], next[target]] = [next[target], next[index]]
        onChange(next)
    }

    const addStep = (): void => {
        onChange([...steps, { type: 'click', selector: '' }])
    }

    return (
        <div className="flex flex-col gap-2">
            {steps.map((step, idx) => {
                const fields = FIELDS_BY_TYPE[step.type] ?? []
                return (
                    <div key={idx} className="border rounded p-2 flex flex-col gap-2 bg-bg-light">
                        <div className="flex items-center gap-2">
                            <span className="text-xs text-muted w-6">#{idx + 1}</span>
                            <LemonSelect
                                value={step.type}
                                onChange={(t) => updateStep(idx, { type: t as SyntheticTestStepType })}
                                options={STEP_TYPES.map((s) => ({ value: s.type, label: s.label }))}
                                size="small"
                                data-attr={`step-${idx}-type`}
                            />
                            <div className="grow" />
                            <LemonButton size="xsmall" onClick={() => moveStep(idx, -1)} disabled={idx === 0}>
                                ↑
                            </LemonButton>
                            <LemonButton
                                size="xsmall"
                                onClick={() => moveStep(idx, 1)}
                                disabled={idx === steps.length - 1}
                            >
                                ↓
                            </LemonButton>
                            <LemonButton size="xsmall" status="danger" onClick={() => removeStep(idx)}>
                                Remove
                            </LemonButton>
                        </div>
                        {fields.map((field) => (
                            <LemonInput
                                key={field}
                                value={(step as any)[field] ?? ''}
                                onChange={(v) =>
                                    updateStep(idx, {
                                        [field]: field === 'duration_ms' ? Number(v) : v,
                                    } as Partial<SyntheticTestStep>)
                                }
                                placeholder={FIELD_PLACEHOLDERS[field]}
                                size="small"
                                data-attr={`step-${idx}-${field}`}
                            />
                        ))}
                    </div>
                )
            })}
            <LemonButton type="secondary" onClick={addStep} data-attr="step-add">
                + Add step
            </LemonButton>
        </div>
    )
}
