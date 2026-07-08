import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonModal } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { endpointSceneLogic } from './endpointSceneLogic'

export function MaterializationSuggestionModal(): JSX.Element {
    const {
        materializationSuggestionModalOpen,
        materializationSuggestion,
        materializationSuggestionLoading,
        suggestionMatchesCurrentQuery,
    } = useValues(endpointSceneLogic)
    const { closeMaterializationSuggestionModal, applyMaterializationSuggestion, regenerateMaterializationSuggestion } =
        useActions(endpointSceneLogic)

    const suggestion = materializationSuggestion
    const hasValidatedSuggestion = suggestion?.suggestion_status === 'ok' && !!suggestion.suggested_query
    const suggestionFailed =
        suggestion?.suggestion_status === 'invalid' || suggestion?.suggestion_status === 'model_error'
    // The error banner already spells out the failed check — repeating it as context is noise
    const showBlocker = !(suggestionFailed && suggestion?.error === suggestion?.original_reason)

    return (
        <LemonModal
            isOpen={materializationSuggestionModalOpen}
            onClose={closeMaterializationSuggestionModal}
            title="Make this endpoint materializable"
            description="AI rewrites your query into an equivalent form that passes our materialization checks. Nothing is saved until you apply the changes and update the endpoint."
            width={768}
            footer={
                <>
                    <LemonButton type="secondary" onClick={closeMaterializationSuggestionModal}>
                        Close
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        onClick={regenerateMaterializationSuggestion}
                        loading={materializationSuggestionLoading}
                        disabledReason={materializationSuggestionLoading ? 'Waiting for the suggestion' : undefined}
                        tooltip="Ask the AI for a fresh rewrite, replacing this suggestion"
                    >
                        Regenerate
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        onClick={applyMaterializationSuggestion}
                        disabledReason={
                            materializationSuggestionLoading
                                ? 'Waiting for the suggestion'
                                : !hasValidatedSuggestion
                                  ? 'No validated suggestion to apply'
                                  : suggestionMatchesCurrentQuery
                                    ? 'Your query already matches this suggestion'
                                    : undefined
                        }
                    >
                        Apply changes to query
                    </LemonButton>
                </>
            }
        >
            <div className="flex flex-col gap-3">
                {materializationSuggestionLoading ? (
                    <div className="flex items-center gap-2 py-8 justify-center text-muted">
                        <Spinner />
                        <span>Analyzing your query against the materialization rules…</span>
                    </div>
                ) : suggestion ? (
                    <>
                        {showBlocker && (
                            <p className="text-secondary text-sm mb-0">Current blocker: {suggestion.original_reason}</p>
                        )}
                        {suggestion.suggestion_status === 'ok' && suggestionMatchesCurrentQuery && (
                            <LemonBanner type="info">
                                Your current query already matches this suggestion — there is nothing to apply. If you
                                haven't saved yet, update the endpoint to create the new version.
                            </LemonBanner>
                        )}
                        {suggestion.suggestion_status === 'ok' && !suggestionMatchesCurrentQuery && (
                            <>
                                {suggestion.explanation && (
                                    <LemonMarkdown lowKeyHeadings disableImages>
                                        {suggestion.explanation}
                                    </LemonMarkdown>
                                )}
                                <CodeSnippet language={Language.SQL} wrap>
                                    {suggestion.suggested_query ?? ''}
                                </CodeSnippet>
                                <p className="text-muted text-xs mb-0">
                                    This rewrite passes the live materialization checks and keeps your variables
                                    unchanged. Review it carefully — applying it and saving creates a new version.
                                </p>
                            </>
                        )}
                        {suggestion.suggestion_status === 'cannot_fix' && (
                            <LemonBanner type="info">
                                <LemonMarkdown lowKeyHeadings disableImages>
                                    {suggestion.explanation ||
                                        'No semantically equivalent rewrite exists for this query.'}
                                </LemonMarkdown>
                            </LemonBanner>
                        )}
                        {suggestionFailed && (
                            <>
                                <LemonBanner type="error">
                                    Couldn't produce a rewrite that passes the checks
                                    {suggestion.error ? `: ${suggestion.error}` : '.'}
                                </LemonBanner>
                                {suggestion.suggested_query && (
                                    <>
                                        <p className="mb-0">
                                            Last attempt (did not pass validation — shown as a starting point):
                                        </p>
                                        <CodeSnippet language={Language.SQL} wrap>
                                            {suggestion.suggested_query}
                                        </CodeSnippet>
                                    </>
                                )}
                            </>
                        )}
                    </>
                ) : (
                    <LemonBanner type="error">
                        The suggestion request failed. Check that AI data processing is enabled for your organization,
                        then try again.
                    </LemonBanner>
                )}
            </div>
        </LemonModal>
    )
}
