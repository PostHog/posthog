import { useActions, useMountedLogic, useValues } from 'kea'

import { LemonButton, LemonInput, LemonModal, LemonSelect, LemonTextArea, Spinner } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { traceReviewModalLogic } from './traceReviewModalLogic'
import type { TraceReviewFormScoreMode, TraceReviewScoreLabel } from './types'

const SCORE_MODE_OPTIONS: { value: TraceReviewFormScoreMode; label: string }[] = [
    { value: 'none', label: 'No score' },
    { value: 'label', label: 'Good or bad' },
    { value: 'numeric', label: 'Numeric' },
]

const SCORE_LABEL_OPTIONS: { value: TraceReviewScoreLabel; label: string }[] = [
    { value: 'good', label: 'Good' },
    { value: 'bad', label: 'Bad' },
]

export function TraceReviewButton({ traceId }: { traceId: string }): JSX.Element {
    const logic = useMountedLogic(traceReviewModalLogic({ traceId }))
    const { featureFlags } = useValues(featureFlagLogic)
    const {
        openModal,
        closeModal,
        saveCurrentReview,
        removeCurrentReview,
        setScoreMode,
        setScoreLabel,
        setScoreNumeric,
        setComment,
    } = useActions(logic)
    const {
        isOpen,
        currentReview,
        currentReviewLoading,
        saving,
        removing,
        scoreMode,
        scoreLabel,
        scoreNumeric,
        comment,
        canSave,
    } = useValues(logic)

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
                    Review trace
                </LemonButton>
            </AccessControlAction>

            <LemonModal isOpen={isOpen} onClose={closeModal} title="Review trace" width={560}>
                {currentReviewLoading ? (
                    <div className="py-12 flex justify-center">
                        <Spinner />
                    </div>
                ) : (
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <div className="text-sm font-medium">Score</div>
                            <LemonSelect
                                value={scoreMode}
                                onChange={(value) => setScoreMode(value as TraceReviewFormScoreMode)}
                                options={SCORE_MODE_OPTIONS}
                                fullWidth
                            />
                        </div>

                        {scoreMode === 'label' ? (
                            <div className="space-y-2">
                                <div className="text-sm font-medium">Label</div>
                                <LemonSelect
                                    value={scoreLabel}
                                    onChange={(value) => setScoreLabel(value as TraceReviewScoreLabel | null)}
                                    options={SCORE_LABEL_OPTIONS}
                                    placeholder="Select a score"
                                    allowClear
                                    fullWidth
                                />
                            </div>
                        ) : null}

                        {scoreMode === 'numeric' ? (
                            <div className="space-y-2">
                                <div className="text-sm font-medium">Numeric score</div>
                                <LemonInput
                                    type="number"
                                    value={scoreNumeric ? Number(scoreNumeric) : undefined}
                                    onChange={(value) =>
                                        setScoreNumeric(value === undefined || Number.isNaN(value) ? '' : String(value))
                                    }
                                    step="any"
                                    placeholder="Enter a numeric score"
                                    fullWidth
                                />
                            </div>
                        ) : null}

                        <div className="space-y-2">
                            <div className="text-sm font-medium">Comment</div>
                            <LemonTextArea
                                value={comment}
                                onChange={setComment}
                                placeholder="Add optional reasoning or notes"
                                rows={4}
                            />
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
