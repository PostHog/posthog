import { useActions, useValues } from 'kea'

import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonCheckbox, LemonSelect } from '@posthog/lemon-ui'

import { LemonModalContent, LemonModalFooter, LemonModalHeader } from 'lib/lemon-ui/LemonModal/LemonModal'
import { LemonModal } from 'lib/lemon-ui/LemonModal/LemonModal'

import type { TemplatesEnumApi } from '../../../experiments/frontend/generated/api.schemas'
import { MAX_VERSIONS, createPromptExperimentModalLogic } from './createPromptExperimentModalLogic'

function variantLabel(index: number): string {
    return index === 0 ? 'Control' : `Variant ${index + 1}`
}

export function CreatePromptExperimentModal(): JSX.Element | null {
    const {
        isModalOpen,
        promptName,
        promptVersions,
        versionSlots,
        selectedTemplates,
        templates,
        templatesLoading,
        canSubmit,
        isSubmitting,
        disabledVersionsByIndex,
        canAddSlot,
    } = useValues(createPromptExperimentModalLogic)
    const { closeModal, setVersionAt, addVersionSlot, removeVersionSlot, toggleTemplate, submitCreate } = useActions(
        createPromptExperimentModalLogic
    )

    if (!isModalOpen) {
        return null
    }

    return (
        <LemonModal isOpen onClose={closeModal} simple maxWidth="38rem">
            <LemonModalHeader>
                <h3>Create experiment{promptName ? ` for "${promptName}"` : ''}</h3>
            </LemonModalHeader>

            <LemonModalContent className="space-y-4">
                {promptVersions.length < 2 ? (
                    <LemonBanner type="warning">
                        This prompt has fewer than two versions. Publish another version before creating an experiment.
                    </LemonBanner>
                ) : null}

                <div className="space-y-2">
                    <label className="text-sm font-medium">Prompt versions</label>
                    <p className="text-secondary text-xs">
                        Pick the versions to compare. The first version is the control variant. The metric template is
                        applied to events tagged with this prompt name.
                    </p>
                    <div className="flex flex-col gap-2">
                        {versionSlots.map((value, index) => {
                            const disabled = disabledVersionsByIndex[index] ?? new Set<number>()
                            const options = promptVersions.map((v) => ({
                                label: `v${v.version}${v.is_latest ? ' (latest)' : ''}`,
                                value: v.version,
                                disabledReason: disabled.has(v.version)
                                    ? 'Already selected for another variant'
                                    : undefined,
                            }))
                            return (
                                <div
                                    key={index}
                                    className="flex items-center gap-2"
                                    data-attr={`llma-prompt-experiment-version-row-${index}`}
                                >
                                    <div className="w-24 text-sm font-medium">{variantLabel(index)}</div>
                                    <LemonSelect<number | null>
                                        className="flex-1"
                                        value={value}
                                        placeholder="Pick a version"
                                        options={options}
                                        onChange={(v) => setVersionAt(index, v ?? null)}
                                        data-attr={`llma-prompt-experiment-version-select-${index}`}
                                    />
                                    <LemonButton
                                        icon={<IconTrash />}
                                        size="small"
                                        type="tertiary"
                                        status="danger"
                                        onClick={() => removeVersionSlot(index)}
                                        disabledReason={
                                            versionSlots.length <= 2 ? 'Need at least two variants' : undefined
                                        }
                                        data-attr={`llma-prompt-experiment-remove-variant-${index}`}
                                    />
                                </div>
                            )
                        })}
                    </div>
                    <div>
                        <LemonButton
                            icon={<IconPlus />}
                            type="secondary"
                            size="small"
                            onClick={addVersionSlot}
                            disabledReason={
                                versionSlots.length >= MAX_VERSIONS
                                    ? `Maximum ${MAX_VERSIONS} variants`
                                    : !canAddSlot
                                      ? 'Fill all variants before adding more'
                                      : undefined
                            }
                            data-attr="llma-prompt-experiment-add-variant"
                        >
                            Add variant
                        </LemonButton>
                    </div>
                </div>

                <div className="space-y-2">
                    <label className="text-sm font-medium">Metrics</label>
                    <p className="text-secondary text-xs">
                        Pick one or more metric templates to attach as primary metrics. Each becomes a separate metric
                        scoped to this prompt.
                    </p>
                    {templatesLoading ? (
                        <p className="text-secondary text-xs">Loading templates…</p>
                    ) : (
                        <div className="flex flex-col gap-2">
                            {templates.map((t) => {
                                const key = t.key as TemplatesEnumApi
                                return (
                                    <div
                                        key={t.key}
                                        className="flex items-start gap-2"
                                        data-attr={`llma-prompt-experiment-template-row-${t.key}`}
                                    >
                                        <LemonCheckbox
                                            checked={selectedTemplates.includes(key)}
                                            onChange={() => toggleTemplate(key)}
                                            data-attr={`llma-prompt-experiment-template-checkbox-${t.key}`}
                                            label={
                                                <span className="flex flex-col">
                                                    <span className="text-sm font-medium">{t.label}</span>
                                                    <span className="text-secondary text-xs">{t.description}</span>
                                                </span>
                                            }
                                        />
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>
            </LemonModalContent>

            <LemonModalFooter>
                <LemonButton
                    type="secondary"
                    onClick={closeModal}
                    disabledReason={isSubmitting ? 'Creating…' : undefined}
                    data-attr="llma-prompt-experiment-cancel"
                >
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={submitCreate}
                    loading={isSubmitting}
                    disabledReason={
                        canSubmit ? undefined : 'Pick at least two distinct versions and one metric template'
                    }
                    data-attr="llma-prompt-experiment-submit"
                >
                    Create experiment
                </LemonButton>
            </LemonModalFooter>
        </LemonModal>
    )
}
