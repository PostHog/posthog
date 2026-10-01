import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconCheck, IconPlus, IconSparkles } from '@posthog/icons'
import {
    LemonBanner,
    LemonButton,
    LemonCard,
    LemonCollapse,
    LemonDialog,
    LemonModal,
    LemonSkeleton,
    LemonTag,
    LemonTextArea,
    Spinner,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import { MAX_RUBRIC_CONTEXT_LENGTH, MAX_SCOUT_RUBRICS, scoutRubricsLogic } from '../../../logics/scoutRubricsLogic'
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
    const [focusExpanded, setFocusExpanded] = useState(false)
    const {
        rubricDocument,
        rubricDocumentLoading,
        criteriaToSave,
        customCriteria,
        sharedCriteria,
        draftRevision,
        expandedCriterionId,
        generation,
        generationActive,
        generationContext,
        generationSubmitting,
        generationError,
        generationElapsedLabel,
        availableSuggestions,
        selectedSuggestionIds,
        allSuggestionsSelected,
        newCriteriaCount,
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
        updateSuggestion,
        removeCriterion,
        addCriterion,
        setExpandedCriterion,
        toggleSuggestion,
        toggleAllSuggestions,
        generateSuggestions,
        setGenerationContext,
        saveRubrics,
    } = useActions(logic)

    const confirmDiscard = (action: () => void): void => {
        if (!hasUnsavedChanges && !generationContext.trim()) {
            action()
            return
        }
        LemonDialog.open({
            title: 'Discard unsaved changes?',
            description: 'Your saved rubrics and generated suggestions will still be available.',
            primaryButton: { children: 'Discard changes', status: 'danger', onClick: action },
            secondaryButton: { children: 'Keep editing' },
        })
    }

    const confirmReplaceSuggestions = (): void => {
        if (generation?.status !== 'completed' || !availableSuggestions.length) {
            generateSuggestions()
            return
        }
        LemonDialog.open({
            title: 'Replace current suggestions?',
            description: 'New suggestions replace the unsaved ones. To keep any, select and save them first.',
            primaryButton: { children: 'Generate new suggestions', onClick: () => generateSuggestions() },
            secondaryButton: { children: 'Keep current suggestions' },
        })
    }

    return (
        <LemonModal
            isOpen
            title={`${scoutName} rubrics`}
            description="Rubrics define how this scout's work is evaluated. Saving them does not change the scout's instructions."
            width={880}
            hasUnsavedInput={hasUnsavedChanges || !!generationContext.trim()}
            onClose={() => confirmDiscard(onClose)}
            closable={!saving}
            data-attr="scout-rubrics-modal"
            footer={
                <div className="flex w-full flex-wrap items-center justify-between gap-3">
                    <span className="flex items-center gap-2 text-sm text-secondary">
                        {draftRevision !== null && draftRevision > 0 && !hasUnsavedChanges && <IconCheck />}
                        <span>
                            {draftRevision === null
                                ? ''
                                : hasUnsavedChanges
                                  ? 'Unsaved changes'
                                  : draftRevision === 0
                                    ? 'Shared defaults are ready to save'
                                    : `All changes saved · Revision ${draftRevision}`}
                        </span>
                    </span>
                    <div className="ml-auto flex flex-wrap gap-2">
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
                            {newCriteriaCount > 0 ? `Save rubrics (${newCriteriaCount} new)` : 'Save rubrics'}
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <div className="flex min-w-0 flex-col gap-7 pb-3">
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
                        <LemonCard hoverEffect={false} className="overflow-hidden p-0">
                            {generationActive ? (
                                <div className="flex items-start gap-3 p-4">
                                    <Spinner className="mt-0.5 shrink-0 text-lg" />
                                    <div className="min-w-0">
                                        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                                            <h4 className="mb-0" role="status">
                                                Generating suggestions…
                                            </h4>
                                            {generationElapsedLabel && (
                                                <span className="text-sm tabular-nums text-secondary" translate="no">
                                                    {`${generationElapsedLabel} elapsed`}
                                                </span>
                                            )}
                                        </div>
                                        <p className="mb-0 mt-1 text-sm text-secondary">
                                            This usually takes a few minutes. You can keep editing or close this window.
                                            Suggestions will appear here when they're ready.
                                        </p>
                                        {generation?.context && (
                                            <p
                                                className="mb-0 mt-2 truncate text-xs text-secondary"
                                                title={generation.context}
                                            >
                                                <strong>Additional focus: </strong>
                                                <span>{generation.context}</span>
                                            </p>
                                        )}
                                    </div>
                                </div>
                            ) : (
                                <>
                                    <div className="flex flex-wrap items-center justify-between gap-4 p-4">
                                        <div className="min-w-0 flex-1 basis-80">
                                            <h4 className="mb-1">Suggest criteria</h4>
                                            <p className="mb-0 text-sm text-secondary">
                                                Drafts criteria from this scout's instructions and any recent runs. It
                                                takes a few minutes, and you can close this window while it works.
                                            </p>
                                        </div>
                                        <LemonButton
                                            type="secondary"
                                            icon={<IconSparkles />}
                                            onClick={confirmReplaceSuggestions}
                                            loading={generationSubmitting}
                                            disabledReason={
                                                saving
                                                    ? 'Saving rubrics'
                                                    : hasUnsavedChanges
                                                      ? 'Save rubric changes before generating suggestions'
                                                      : undefined
                                            }
                                            data-attr="scout-rubrics-generate"
                                        >
                                            {generation?.status === 'completed'
                                                ? 'Generate again'
                                                : 'Generate suggestions'}
                                        </LemonButton>
                                    </div>
                                    <div className="border-t bg-surface-secondary">
                                        <LemonCollapse
                                            embedded
                                            size="small"
                                            activeKey={focusExpanded ? 'focus' : null}
                                            onChange={(key) => setFocusExpanded(key !== null)}
                                            panels={[
                                                {
                                                    key: 'focus',
                                                    dataAttr: 'scout-rubrics-focus-toggle',
                                                    header: (
                                                        <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-2 gap-y-1 text-sm">
                                                            <span>Additional focus</span>
                                                            <span className="font-normal text-secondary">Optional</span>
                                                            {!focusExpanded && generationContext.trim() && (
                                                                <span className="ml-auto min-w-0 max-w-full truncate font-normal text-secondary">
                                                                    {generationContext.trim()}
                                                                </span>
                                                            )}
                                                        </span>
                                                    ),
                                                    className: 'px-4! pb-4!',
                                                    content: (
                                                        <div className="flex flex-col gap-2">
                                                            <LemonField.Pure
                                                                label="What should suggestions pay extra attention to?"
                                                                htmlFor="scout-rubrics-focus"
                                                            >
                                                                <LemonTextArea
                                                                    id="scout-rubrics-focus"
                                                                    value={generationContext}
                                                                    onChange={setGenerationContext}
                                                                    placeholder="e.g. Check that comparisons use consistent filters and enough data."
                                                                    minRows={3}
                                                                    maxRows={8}
                                                                    maxLength={MAX_RUBRIC_CONTEXT_LENGTH}
                                                                    disabled={saving || generationSubmitting}
                                                                    data-attr="scout-rubrics-focus"
                                                                />
                                                            </LemonField.Pure>
                                                            <p className="mb-0 text-xs text-secondary">
                                                                Used for this generation only. Suggestions still cover
                                                                the scout's full scope.
                                                            </p>
                                                        </div>
                                                    ),
                                                },
                                            ]}
                                        />
                                    </div>
                                </>
                            )}
                        </LemonCard>

                        {(generationError || generation?.status === 'failed') && (
                            <LemonBanner type="error">
                                {generationError ||
                                    generation?.error ||
                                    'Generation failed. Try generating suggestions again.'}
                            </LemonBanner>
                        )}

                        {generation?.status === 'completed' && (
                            <section className="min-w-0" aria-label="Suggestions">
                                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                                    <div className="min-w-0 flex-1 basis-80">
                                        <h4 className="mb-1 flex items-center gap-2">
                                            <span>Suggestions</span>
                                            <LemonTag type="muted">{availableSuggestions.length}</LemonTag>
                                        </h4>
                                        <p className="mb-0 text-sm text-secondary">
                                            {availableSuggestions.length
                                                ? 'Select the ones you want. Selected suggestions are added to this scout when you save rubrics.'
                                                : generation.suggestions.length
                                                  ? 'All suggestions are in your rubric.'
                                                  : 'No additional criteria were suggested. You can add criteria manually below.'}
                                        </p>
                                    </div>
                                    {availableSuggestions.length > 0 && (
                                        <LemonButton
                                            type="tertiary"
                                            size="small"
                                            onClick={() => toggleAllSuggestions(!allSuggestionsSelected)}
                                            disabledReason={saving ? 'Saving rubrics' : undefined}
                                            data-attr="scout-rubrics-select-all"
                                        >
                                            {allSuggestionsSelected ? 'Clear selection' : 'Select all'}
                                        </LemonButton>
                                    )}
                                </div>
                                {availableSuggestions.length > 0 && (
                                    <LemonCard
                                        hoverEffect={false}
                                        className="divide-y overflow-hidden border-accent-highlight-secondary bg-warning-highlight p-0"
                                    >
                                        {availableSuggestions.map((suggestion) => (
                                            <ScoutRubricCriterionEditor
                                                key={suggestion.id}
                                                criterion={suggestion}
                                                selected={selectedSuggestionIds.includes(suggestion.id)}
                                                onSelect={(selected) => toggleSuggestion(suggestion.id, selected)}
                                                expanded={expandedCriterionId === suggestion.id}
                                                saving={saving}
                                                onChange={(changes) => updateSuggestion(suggestion.id, changes)}
                                                onExpand={() => {
                                                    if (expandedCriterionId !== suggestion.id) {
                                                        toggleSuggestion(suggestion.id, true)
                                                    }
                                                    setExpandedCriterion(
                                                        expandedCriterionId === suggestion.id ? null : suggestion.id
                                                    )
                                                }}
                                                onRemove={() => {}}
                                            />
                                        ))}
                                    </LemonCard>
                                )}
                            </section>
                        )}

                        {[
                            {
                                title: 'This scout',
                                description: 'Criteria written for this scout only.',
                                criteria: customCriteria,
                                custom: true,
                            },
                            {
                                title: 'Shared defaults',
                                description:
                                    'Used by every scout. Editing or turning one off here only affects this scout.',
                                criteria: sharedCriteria,
                                custom: false,
                            },
                        ].map(({ title, description, criteria, custom }) => (
                            <section key={title} className="min-w-0" aria-label={title}>
                                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                                    <div className="min-w-0 flex-1 basis-80">
                                        <h4 className="mb-1 flex items-center gap-2">
                                            <span>{title}</span>
                                            <LemonTag type="muted">{criteria.length}</LemonTag>
                                        </h4>
                                        <p className="mb-0 text-sm text-secondary">{description}</p>
                                    </div>
                                    {custom && (
                                        <LemonButton
                                            type="secondary"
                                            size="small"
                                            icon={<IconPlus />}
                                            onClick={addCriterion}
                                            disabledReason={
                                                saving
                                                    ? 'Saving rubrics'
                                                    : criteriaToSave.length >= MAX_SCOUT_RUBRICS
                                                      ? `Keep at most ${MAX_SCOUT_RUBRICS} criteria`
                                                      : undefined
                                            }
                                            data-attr="scout-rubrics-add"
                                        >
                                            Add criterion
                                        </LemonButton>
                                    )}
                                </div>
                                <LemonCard hoverEffect={false} className="divide-y overflow-hidden p-0">
                                    {criteria.length === 0 && (
                                        <p className="m-0 p-6 text-center text-sm text-secondary">
                                            No scout-specific criteria yet. Add one, or generate suggestions.
                                        </p>
                                    )}
                                    {criteria.map((criterion) => (
                                        <ScoutRubricCriterionEditor
                                            key={criterion.id}
                                            criterion={criterion}
                                            expanded={expandedCriterionId === criterion.id}
                                            saving={saving}
                                            onChange={(changes) => updateCriterion(criterion.id, changes)}
                                            onExpand={() =>
                                                setExpandedCriterion(
                                                    expandedCriterionId === criterion.id ? null : criterion.id
                                                )
                                            }
                                            onRemove={() => removeCriterion(criterion.id)}
                                        />
                                    ))}
                                </LemonCard>
                            </section>
                        ))}

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
