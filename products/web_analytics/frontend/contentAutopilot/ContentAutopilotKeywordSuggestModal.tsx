import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonModal,
    LemonSelect,
    LemonTag,
    LemonTextArea,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { pluralize } from 'lib/utils/strings'

import type { AEOKeywordSuggestionApi } from 'products/web_analytics/frontend/generated/api.schemas'
import {
    aeoKeywordsSuggestBodyBrandMax,
    aeoKeywordsSuggestBodyDescriptionMax,
    aeoKeywordsSuggestBodyDomainMax,
} from 'products/web_analytics/frontend/generated/api.zod'

import {
    KEYWORD_SUGGESTION_COUNTS,
    contentAutopilotKeywordSuggestionsLogic,
} from './contentAutopilotKeywordSuggestionsLogic'
import { siteDomain } from './contentAutopilotPromptSuggestionsLogic'

const SuggestionRow = ({ suggestion }: { suggestion: AEOKeywordSuggestionApi }): JSX.Element => {
    const { selectedKeywords } = useValues(contentAutopilotKeywordSuggestionsLogic)
    const { toggleSuggestion } = useActions(contentAutopilotKeywordSuggestionsLogic)

    return (
        <div className="flex gap-2 py-2 border-b last:border-b-0">
            <LemonCheckbox
                checked={selectedKeywords.includes(suggestion.keyword)}
                onChange={() => toggleSuggestion(suggestion.keyword)}
                aria-label={`Select ${suggestion.keyword}`}
            />
            <div className="flex flex-col gap-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1">
                    <span className="font-semibold break-words">{suggestion.keyword}</span>
                    {suggestion.searched_checks > 0 ? (
                        <Tooltip title="Recent answers where the engine searched the web for this keyword.">
                            <LemonTag type="highlight">{`Searched in ${pluralize(suggestion.searched_checks, 'answer')}`}</LemonTag>
                        </Tooltip>
                    ) : null}
                </div>
                {suggestion.reason ? <span className="text-xs text-muted">{suggestion.reason}</span> : null}
            </div>
        </div>
    )
}

const SuggestForm = (): JSX.Element => {
    const { form, startError } = useValues(contentAutopilotKeywordSuggestionsLogic)
    const { setForm } = useActions(contentAutopilotKeywordSuggestionsLogic)

    return (
        <div className="flex flex-col gap-4">
            {startError ? <LemonBanner type="error">{startError}</LemonBanner> : null}
            <LemonField.Pure label="Site" help="PostHog reads this site if your prompts don't say enough about you.">
                <LemonInput
                    value={form.domain}
                    onChange={(domain) => setForm({ domain })}
                    maxLength={aeoKeywordsSuggestBodyDomainMax}
                    placeholder="example.com"
                    autoFocus
                    data-attr="content-autopilot-keyword-suggest-domain"
                />
            </LemonField.Pure>
            <div className="grid grid-cols-1 @md/suggest:grid-cols-2 gap-4">
                <LemonField.Pure label="Brand" help="Optional. Keywords that name it are left out.">
                    <LemonInput
                        value={form.brand}
                        onChange={(brand) => setForm({ brand })}
                        maxLength={aeoKeywordsSuggestBodyBrandMax}
                    />
                </LemonField.Pure>
                <LemonField.Pure label="Number of keywords">
                    <LemonSelect
                        value={form.count}
                        onChange={(count) => setForm({ count })}
                        options={KEYWORD_SUGGESTION_COUNTS.map((count) => ({ value: count, label: String(count) }))}
                    />
                </LemonField.Pure>
            </div>
            <LemonField.Pure label="What you do and who it is for" help="Optional. Read from the site when empty.">
                <LemonTextArea
                    value={form.description}
                    onChange={(description) => setForm({ description })}
                    maxLength={aeoKeywordsSuggestBodyDescriptionMax}
                    minRows={2}
                    placeholder="Open source product analytics for engineers at startups"
                />
            </LemonField.Pure>
        </div>
    )
}

const SuggestReview = (): JSX.Element => {
    const { job, selectedSuggestions } = useValues(contentAutopilotKeywordSuggestionsLogic)
    const { setSelectedKeywords } = useActions(contentAutopilotKeywordSuggestionsLogic)
    const suggestions = job?.suggestions ?? []
    const allSelected = selectedSuggestions.length === suggestions.length

    if (suggestions.length === 0) {
        return (
            <p className="m-0 text-muted">
                No new keywords came back. The ideas may already be on your list, or none were worth keeping. Add a
                description of what you do and try again.
            </p>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-muted">
                    {/* translate="no" keeps the count updating when the browser translates the page. */}
                    <span translate="no">{selectedSuggestions.length}</span> of{' '}
                    {pluralize(suggestions.length, 'suggestion')} selected. Nothing is tracked until you add them.
                </span>
                <LemonButton
                    size="small"
                    type="tertiary"
                    onClick={() => setSelectedKeywords(allSelected ? [] : suggestions.map(({ keyword }) => keyword))}
                >
                    {allSelected ? 'Select none' : 'Select all'}
                </LemonButton>
            </div>
            <div className="max-h-[50vh] overflow-y-auto">
                {suggestions.map((suggestion) => (
                    <SuggestionRow key={suggestion.keyword} suggestion={suggestion} />
                ))}
            </div>
        </div>
    )
}

export const ContentAutopilotKeywordSuggestModal = (): JSX.Element => {
    const { suggestOpen, form, job, jobRef, starting, adding, selectedSuggestions, editingInputs } = useValues(
        contentAutopilotKeywordSuggestionsLogic
    )
    const { closeSuggest, startSuggestions, editRequest, backToSuggestions, addSelected } = useActions(
        contentAutopilotKeywordSuggestionsLogic
    )
    const view = editingInputs || !job ? 'form' : job.status
    const domain = jobRef?.domain || siteDomain(form.domain) || 'your site'

    const footer =
        view === 'completed' ? (
            <>
                <LemonButton
                    type="secondary"
                    onClick={editRequest}
                    disabledReason={adding ? 'Wait for the keywords to save' : undefined}
                >
                    Change inputs
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={addSelected}
                    loading={adding}
                    disabledReason={selectedSuggestions.length === 0 ? 'Select at least one keyword' : undefined}
                    data-attr="content-autopilot-keyword-suggest-add"
                >
                    {selectedSuggestions.length > 0
                        ? `Add ${pluralize(selectedSuggestions.length, 'keyword')}`
                        : 'Add keywords'}
                </LemonButton>
            </>
        ) : view === 'pending' ? (
            <LemonButton type="secondary" onClick={closeSuggest}>
                Close and keep working
            </LemonButton>
        ) : view === 'failed' ? (
            <>
                <LemonButton type="secondary" onClick={editRequest}>
                    Change inputs
                </LemonButton>
                {siteDomain(form.domain) ? (
                    <LemonButton type="primary" onClick={startSuggestions} loading={starting}>
                        Try again
                    </LemonButton>
                ) : null}
            </>
        ) : (
            <>
                {job && job.status !== 'failed' ? (
                    <LemonButton type="secondary" onClick={backToSuggestions}>
                        {job.status === 'pending' ? 'Back to progress' : 'Back to suggestions'}
                    </LemonButton>
                ) : (
                    <LemonButton type="secondary" onClick={closeSuggest}>
                        Cancel
                    </LemonButton>
                )}
                <LemonButton
                    type="primary"
                    onClick={startSuggestions}
                    loading={starting}
                    disabledReason={!siteDomain(form.domain) ? 'Enter your site' : undefined}
                    data-attr="content-autopilot-keyword-suggest-start"
                >
                    Suggest keywords
                </LemonButton>
            </>
        )

    return (
        <LemonModal
            isOpen={suggestOpen}
            onClose={adding ? undefined : closeSuggest}
            title="Suggest keywords"
            description="PostHog suggests keywords from your site, your prompts and the web searches the AI engines ran while answering them. You pick which ones to track."
            width={640}
            footer={footer}
        >
            <div className="@container/suggest">
                {view === 'pending' ? (
                    <div className="flex flex-col items-center gap-3 py-10 text-center">
                        <Spinner className="text-2xl" />
                        <span className="font-semibold">Finding keywords for {domain}</span>
                        <span className="text-muted max-w-md">
                            This usually takes a minute. You can close this and come back. The suggestions keep loading
                            in the background.
                        </span>
                    </div>
                ) : view === 'failed' ? (
                    <LemonBanner type="error">{job?.error || "Couldn't suggest keywords. Try again."}</LemonBanner>
                ) : view === 'completed' ? (
                    <SuggestReview />
                ) : (
                    <div className="flex flex-col gap-3">
                        {editingInputs && job?.status === 'completed' ? (
                            <LemonBanner type="info">
                                Suggesting again replaces the {pluralize(job.suggestions.length, 'suggestion')} you have
                                now.
                            </LemonBanner>
                        ) : null}
                        <SuggestForm />
                    </div>
                )}
            </div>
        </LemonModal>
    )
}
