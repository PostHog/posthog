import { useActions, useValues } from 'kea'

import { IconPlus, IconSparkles } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonCheckbox,
    LemonDialog,
    LemonModal,
    LemonSkeleton,
} from '@posthog/lemon-ui'

import { MAX_SCOUT_RUBRICS, scoutRubricsLogic } from '../../../logics/scoutRubricsLogic'
import { ScoutRubricCriterionEditor } from './ScoutRubricCriterionEditor'

export function ScoutRubricsModal({
    teamId,
    configId,
    scoutName,
    onClose,
}: {
    teamId: number
    configId: string
    scoutName: string
    onClose: () => void
}): JSX.Element {
    const logic = scoutRubricsLogic({ teamId, configId })
    const {
        rubricDocument,
        rubricDocumentLoading,
        draftCriteria,
        draftRevision,
        expandedCriterionId,
        generation,
        generationActive,
        generationSubmitting,
        generationError,
        availableSuggestions,
        selectedSuggestionIds,
        selectedSuggestions,
        hasUnsavedChanges,
        saving,
        saveError,
        saveConflict,
        loadError,
        validationError,
    } = useValues(logic)
    const {
        loadRubrics,
        updateCriterion,
        removeCriterion,
        addCriterion,
        setExpandedCriterion,
        toggleSuggestion,
        addSelectedSuggestions,
        generateSuggestions,
        saveRubrics,
    } = useActions(logic)

    const confirmDiscard = (action: () => void): void => {
        if (!hasUnsavedChanges) {
            action()
            return
        }
        LemonDialog.open({
            title: 'Discard unsaved rubric changes?',
            description: 'Your saved rubrics and generated suggestions will still be available.',
            primaryButton: { children: 'Discard changes', status: 'danger', onClick: action },
            secondaryButton: { children: 'Keep editing' },
        })
    }

    return (
        <LemonModal
            isOpen
            title={`${scoutName} rubrics`}
            description="Define how this scout should be evaluated. Saving rubrics does not change its instructions."
            width={800}
            hasUnsavedInput={hasUnsavedChanges}
            onClose={() => confirmDiscard(onClose)}
            closable={!saving}
            data-attr="scout-rubrics-modal"
            footer={
                <div className="flex w-full flex-wrap items-center justify-between gap-2">
                    <span className="text-sm text-secondary">
                        {draftRevision === null
                            ? ''
                            : hasUnsavedChanges
                              ? 'Unsaved changes'
                              : draftRevision === 0
                                ? 'Shared defaults are ready to save'
                                : `Saved revision ${draftRevision}`}
                    </span>
                    <div className="flex flex-wrap gap-2">
                        <LemonButton
                            type="secondary"
                            onClick={() => confirmDiscard(onClose)}
                            disabledReason={saving ? 'Saving rubrics' : undefined}
                        >
                            Close
                        </LemonButton>
                        <LemonButton
                            type="primary"
                            onClick={saveRubrics}
                            loading={saving}
                            disabledReason={
                                draftRevision === null
                                    ? 'Load the rubrics first'
                                    : saveConflict
                                      ? 'Reload the saved version first'
                                      : validationError ||
                                        (!hasUnsavedChanges && draftRevision > 0 ? 'No unsaved changes' : undefined)
                            }
                            data-attr="scout-rubrics-save"
                        >
                            Save rubrics
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="flex min-w-0 flex-col gap-4">
                {loadError && (
                    <LemonBanner
                        type="error"
                        action={{ children: 'Retry', onClick: () => loadRubrics(), loading: rubricDocumentLoading }}
                    >
                        {loadError}
                    </LemonBanner>
                )}
                {!rubricDocument && !loadError ? (
                    <LemonSkeleton className="h-40 w-full" />
                ) : rubricDocument ? (
                    <>
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <p className="mb-0 max-w-md text-sm text-secondary">
                                Shared defaults start enabled. Adjust them for this scout and add your own criteria.
                                Generate suggestions from its instructions and recent runs when you need a starting
                                point.
                            </p>
                            <LemonButton
                                type="secondary"
                                icon={<IconSparkles />}
                                onClick={generateSuggestions}
                                loading={generationSubmitting || generationActive}
                                disabledReason={
                                    generationActive
                                        ? 'Suggestions are being generated'
                                        : saving
                                          ? 'Saving rubrics'
                                          : undefined
                                }
                                data-attr="scout-rubrics-generate"
                            >
                                {generationActive ? 'Generating suggestions' : 'Generate suggestions'}
                            </LemonButton>
                        </div>

                        {generationActive && (
                            <LemonBanner type="info">
                                The agent is reviewing this scout and its recent runs. You can leave this page and
                                return later. Suggestions will appear here for you to review.
                            </LemonBanner>
                        )}
                        {(generationError || generation?.status === 'failed') && (
                            <LemonBanner type="error">
                                {generationError ||
                                    generation?.error ||
                                    'Generation failed. Try generating suggestions again.'}
                            </LemonBanner>
                        )}
                        {generation?.status === 'completed' && (
                            <LemonCard hoverEffect={false} className="!p-4">
                                <h3 className="mb-2">Suggested criteria</h3>
                                {generation.summary && (
                                    <p className="break-words text-sm text-secondary">{generation.summary}</p>
                                )}
                                {availableSuggestions.length ? (
                                    <>
                                        <p className="text-sm text-secondary">
                                            Select the suggestions you want to add. You can edit them before saving.
                                        </p>
                                        <div className="flex flex-col gap-4">
                                            {availableSuggestions.map((suggestion) => (
                                                <div key={suggestion.id} className="flex min-w-0 flex-col gap-1">
                                                    <LemonCheckbox
                                                        checked={selectedSuggestionIds.includes(suggestion.id)}
                                                        onChange={(selected) =>
                                                            toggleSuggestion(suggestion.id, selected)
                                                        }
                                                        label={suggestion.title}
                                                        disabledReason={saving ? 'Saving rubrics' : undefined}
                                                        data-attr="scout-rubric-select-suggestion"
                                                    />
                                                    <p className="mb-0 break-words text-sm text-secondary">
                                                        {suggestion.description}
                                                    </p>
                                                    <p className="mb-0 break-words text-sm">
                                                        <strong>Passes when: </strong>
                                                        <span>{suggestion.pass_condition}</span>
                                                    </p>
                                                    <p className="mb-0 break-words text-xs text-secondary">
                                                        <strong>Applies: </strong>
                                                        <span>{suggestion.applicability}</span>
                                                    </p>
                                                </div>
                                            ))}
                                        </div>
                                        <LemonButton
                                            type="secondary"
                                            className="mt-4"
                                            onClick={addSelectedSuggestions}
                                            disabledReason={
                                                saving
                                                    ? 'Saving rubrics'
                                                    : !selectedSuggestions.length
                                                      ? 'Select at least one suggestion'
                                                      : selectedSuggestions.length + draftCriteria.length >
                                                          MAX_SCOUT_RUBRICS
                                                        ? `Keep at most ${MAX_SCOUT_RUBRICS} criteria`
                                                        : undefined
                                            }
                                            data-attr="scout-rubrics-add-selected"
                                        >
                                            {`Add selected (${selectedSuggestions.length})`}
                                        </LemonButton>
                                    </>
                                ) : (
                                    <p className="mb-0 text-sm text-secondary">
                                        {generation.suggestions.length
                                            ? 'All suggestions are in your rubric. Review them below and save your changes.'
                                            : 'No additional criteria were suggested. You can add criteria manually below.'}
                                    </p>
                                )}
                            </LemonCard>
                        )}

                        <div className="flex flex-wrap items-center justify-between gap-2">
                            <h3 className="mb-0">{`Criteria (${draftCriteria.length})`}</h3>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconPlus />}
                                onClick={addCriterion}
                                disabledReason={
                                    saving
                                        ? 'Saving rubrics'
                                        : draftCriteria.length >= MAX_SCOUT_RUBRICS
                                          ? `Keep at most ${MAX_SCOUT_RUBRICS} criteria`
                                          : undefined
                                }
                                data-attr="scout-rubrics-add"
                            >
                                Add criterion
                            </LemonButton>
                        </div>
                        {draftCriteria.length === 0 && (
                            <p className="mb-0 text-sm text-secondary">
                                No criteria yet. Add a criterion or generate suggestions to get started.
                            </p>
                        )}
                        <div className="flex flex-col gap-2">
                            {draftCriteria.map((criterion) => (
                                <ScoutRubricCriterionEditor
                                    key={criterion.id}
                                    criterion={criterion}
                                    expanded={expandedCriterionId === criterion.id}
                                    saving={saving}
                                    onChange={(changes) => updateCriterion(criterion.id, changes)}
                                    onExpand={() =>
                                        setExpandedCriterion(expandedCriterionId === criterion.id ? null : criterion.id)
                                    }
                                    onRemove={() => removeCriterion(criterion.id)}
                                />
                            ))}
                        </div>
                        {saveError && (
                            <LemonBanner
                                type="error"
                                action={
                                    saveConflict
                                        ? {
                                              children: 'Reload saved version',
                                              loading: rubricDocumentLoading,
                                              onClick: () => confirmDiscard(() => loadRubrics({ resetDraft: true })),
                                          }
                                        : undefined
                                }
                            >
                                {saveError}
                            </LemonBanner>
                        )}
                    </>
                ) : null}
            </div>
        </LemonModal>
    )
}
