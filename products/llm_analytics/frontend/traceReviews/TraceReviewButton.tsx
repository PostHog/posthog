import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal, LemonSegmentedButton, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type {
    BooleanScoreDefinitionConfigApi as BooleanScoreDefinitionConfig,
    CategoricalScoreDefinitionConfigApi as CategoricalScoreDefinitionConfig,
    NumericScoreDefinitionConfigApi as NumericScoreDefinitionConfig,
    ScoreDefinitionApi as ScoreDefinition,
} from '../generated/api.schemas'
import { traceReviewModalLogic } from './traceReviewModalLogic'
import { traceReviewsLazyLoaderLogic } from './traceReviewsLazyLoaderLogic'
import { getBooleanConfig, getCategoricalConfig, getNumericConfig } from './utils'

function CategoricalDefinitionInput({
    definition,
    value,
    setScoreValue,
}: {
    definition: ScoreDefinition
    value: string | boolean | null | undefined
    setScoreValue: (definitionId: string, value: string | boolean | null) => void
}): JSX.Element {
    const config = getCategoricalConfig(definition.config) as CategoricalScoreDefinitionConfig

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <LemonSegmentedButton
                    value={typeof value === 'string' ? value : undefined}
                    onChange={(nextValue) => setScoreValue(definition.id, (nextValue as string | undefined) || null)}
                    options={config.options.map((option) => ({ label: option.label, value: option.key }))}
                    fullWidth
                    size="small"
                />
                {typeof value === 'string' && value ? (
                    <LemonButton type="secondary" size="small" onClick={() => setScoreValue(definition.id, null)}>
                        Clear
                    </LemonButton>
                ) : null}
            </div>
        </div>
    )
}

function BooleanDefinitionInput({
    definition,
    value,
    setScoreValue,
}: {
    definition: ScoreDefinition
    value: string | boolean | null | undefined
    setScoreValue: (definitionId: string, value: string | boolean | null) => void
}): JSX.Element {
    const config = getBooleanConfig(definition.config) as BooleanScoreDefinitionConfig

    return (
        <div className="space-y-2">
            <div className="flex items-center gap-2">
                <LemonSegmentedButton
                    value={typeof value === 'boolean' ? String(value) : undefined}
                    onChange={(nextValue) =>
                        setScoreValue(definition.id, nextValue === 'true' ? true : nextValue === 'false' ? false : null)
                    }
                    options={[
                        { label: config.true_label || 'Yes', value: 'true' },
                        { label: config.false_label || 'No', value: 'false' },
                    ]}
                    fullWidth
                    size="small"
                />
                {typeof value === 'boolean' ? (
                    <LemonButton type="secondary" size="small" onClick={() => setScoreValue(definition.id, null)}>
                        Clear
                    </LemonButton>
                ) : null}
            </div>
        </div>
    )
}

function NumericDefinitionInput({
    definition,
    value,
    setScoreValue,
}: {
    definition: ScoreDefinition
    value: string | boolean | null | undefined
    setScoreValue: (definitionId: string, value: string | boolean | null) => void
}): JSX.Element {
    const config = getNumericConfig(definition.config) as NumericScoreDefinitionConfig

    return (
        <div className="flex items-center gap-2">
            <LemonInput
                type="number"
                value={typeof value === 'string' && value ? Number(value) : undefined}
                onChange={(nextValue) =>
                    setScoreValue(
                        definition.id,
                        nextValue === undefined || Number.isNaN(nextValue) ? '' : String(nextValue)
                    )
                }
                min={config.min ?? undefined}
                max={config.max ?? undefined}
                step={config.step ?? 'any'}
                placeholder="Enter a numeric score"
                fullWidth
            />
            {typeof value === 'string' && value ? (
                <LemonButton type="secondary" size="small" onClick={() => setScoreValue(definition.id, '')}>
                    Clear
                </LemonButton>
            ) : null}
        </div>
    )
}

function DefinitionInput({
    definition,
    value,
    setScoreValue,
}: {
    definition: ScoreDefinition
    value: string | boolean | null | undefined
    setScoreValue: (definitionId: string, value: string | boolean | null) => void
}): JSX.Element {
    if (definition.kind === 'categorical') {
        return <CategoricalDefinitionInput definition={definition} value={value} setScoreValue={setScoreValue} />
    }

    if (definition.kind === 'numeric') {
        return <NumericDefinitionInput definition={definition} value={value} setScoreValue={setScoreValue} />
    }

    return <BooleanDefinitionInput definition={definition} value={value} setScoreValue={setScoreValue} />
}

export function TraceReviewButton({ traceId }: { traceId: string }): JSX.Element {
    const logic = useMountedLogic(traceReviewModalLogic({ traceId }))
    const { featureFlags } = useValues(featureFlagLogic)
    const { getTraceReview } = useValues(traceReviewsLazyLoaderLogic)
    const { openModal, closeModal, saveCurrentReview, removeCurrentReview, setScoreValue, setComment } =
        useActions(logic)
    const {
        isOpen,
        currentReview,
        activeDefinitions,
        modalDataLoading,
        saving,
        removing,
        scoreValues,
        comment,
        canSave,
    } = useValues(logic)
    const cachedReview = getTraceReview(traceId)
    const effectiveReview = cachedReview === undefined ? currentReview : cachedReview
    const buttonLabel = effectiveReview ? 'Edit review' : 'Review trace'
    const modalTitle = effectiveReview ? 'Edit review' : 'Review trace'

    if (!featureFlags[FEATURE_FLAGS.LLM_ANALYTICS_TRACE_REVIEW]) {
        return <></>
    }

    return (
        <>
            <AccessControlAction
                resourceType={AccessControlResourceType.LlmAnalytics}
                minAccessLevel={AccessControlLevel.Editor}
            >
                <LemonButton type="secondary" size="xsmall" onClick={openModal} data-attr="review-trace-button">
                    {buttonLabel}
                </LemonButton>
            </AccessControlAction>

            <LemonModal isOpen={isOpen} onClose={closeModal} title={modalTitle} width={680}>
                {modalDataLoading ? (
                    <div className="py-12 flex justify-center">
                        <Spinner />
                    </div>
                ) : (
                    <div className="space-y-4">
                        {activeDefinitions.length === 0 ? (
                            <div className="text-sm text-muted">
                                There are no active scorers yet. You can still mark this trace as reviewed and add
                                reasoning.
                            </div>
                        ) : (
                            <div className="space-y-4">
                                {activeDefinitions.map((definition) => (
                                    <div key={definition.id} className="space-y-2">
                                        <div className="space-y-1">
                                            <div className="text-sm font-medium">{definition.name}</div>
                                            {definition.description ? (
                                                <div className="text-xs text-muted">{definition.description}</div>
                                            ) : null}
                                        </div>
                                        <DefinitionInput
                                            definition={definition}
                                            value={scoreValues[definition.id]}
                                            setScoreValue={setScoreValue}
                                        />
                                    </div>
                                ))}
                            </div>
                        )}

                        <div className="space-y-2">
                            <div className="text-sm font-medium">Reasoning (optional)</div>
                            <LemonTextArea
                                value={comment}
                                onChange={setComment}
                                placeholder="Add optional reasoning or notes"
                                rows={4}
                            />
                            <div className="text-xs text-muted">
                                Leave this blank if you only want to mark the trace as reviewed.
                            </div>
                        </div>

                        <div className="flex items-center justify-between gap-2 pt-2">
                            <div>
                                {currentReview ? (
                                    <LemonButton
                                        type="secondary"
                                        status="danger"
                                        onClick={removeCurrentReview}
                                        loading={removing}
                                        disabled={saving}
                                        data-attr="remove-trace-review-button"
                                    >
                                        Remove review
                                    </LemonButton>
                                ) : null}
                            </div>
                            <div className="flex items-center gap-2">
                                <LemonButton type="secondary" onClick={closeModal} disabled={saving || removing}>
                                    Cancel
                                </LemonButton>
                                <LemonButton
                                    type="primary"
                                    onClick={saveCurrentReview}
                                    loading={saving}
                                    disabled={!canSave || removing}
                                    data-attr="save-trace-review-button"
                                >
                                    Save review
                                </LemonButton>
                            </div>
                        </div>
                    </div>
                )}
            </LemonModal>
        </>
    )
}
