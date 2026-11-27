import { useActions, useValues } from 'kea'
import { useId } from 'react'

import {
    Button,
    Checkbox,
    Credenza,
    CredenzaBody,
    CredenzaContent,
    CredenzaDescription,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    Field,
    FieldDescription,
    FieldLabel,
    Input,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Spinner,
    Text,
    Textarea,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import type { AEOKeywordSuggestionApi } from 'products/web_analytics/frontend/generated/api.schemas'
import {
    aeoKeywordsSuggestBodyBrandMax,
    aeoKeywordsSuggestBodyDescriptionMax,
    aeoKeywordsSuggestBodyDomainMax,
} from 'products/web_analytics/frontend/generated/api.zod'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityTag } from './AiVisibilityTag'
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
            <Checkbox
                checked={selectedKeywords.includes(suggestion.keyword)}
                onCheckedChange={() => toggleSuggestion(suggestion.keyword)}
                aria-label={`Select ${suggestion.keyword}`}
                className="mt-0.5"
            />
            <div className="flex flex-col gap-1 min-w-0">
                <div className="flex flex-wrap items-center gap-1">
                    <Text size="xs" weight="semibold" render={<span className="break-words" />}>
                        {suggestion.keyword}
                    </Text>
                    {suggestion.searched_checks > 0 ? (
                        <Tooltip>
                            <TooltipTrigger render={<span />}>
                                <AiVisibilityTag type="highlight">{`Searched in ${pluralize(suggestion.searched_checks, 'answer')}`}</AiVisibilityTag>
                            </TooltipTrigger>
                            <TooltipContent>
                                Recent answers where the engine searched the web for this keyword.
                            </TooltipContent>
                        </Tooltip>
                    ) : null}
                </div>
                {suggestion.reason ? (
                    <Text size="xs" variant="muted" render={<span />}>
                        {suggestion.reason}
                    </Text>
                ) : null}
            </div>
        </div>
    )
}

const SuggestForm = (): JSX.Element => {
    const { form, startError } = useValues(contentAutopilotKeywordSuggestionsLogic)
    const { setForm } = useActions(contentAutopilotKeywordSuggestionsLogic)
    const id = useId()

    return (
        <div className="flex flex-col gap-4">
            {startError ? <AiVisibilityBanner type="error">{startError}</AiVisibilityBanner> : null}
            <Field>
                <FieldLabel htmlFor={`${id}-domain`}>Site</FieldLabel>
                <Input
                    id={`${id}-domain`}
                    value={form.domain}
                    onChange={(event) => setForm({ domain: event.target.value })}
                    maxLength={aeoKeywordsSuggestBodyDomainMax}
                    placeholder="example.com"
                    autoFocus
                    data-attr="content-autopilot-keyword-suggest-domain"
                />
                <FieldDescription>PostHog reads this site if your prompts don't say enough about you.</FieldDescription>
            </Field>
            <div className="grid grid-cols-1 @md/suggest:grid-cols-2 gap-4">
                <Field>
                    <FieldLabel htmlFor={`${id}-brand`}>Brand</FieldLabel>
                    <Input
                        id={`${id}-brand`}
                        value={form.brand}
                        onChange={(event) => setForm({ brand: event.target.value })}
                        maxLength={aeoKeywordsSuggestBodyBrandMax}
                    />
                    <FieldDescription>Optional. Keywords that name it are left out.</FieldDescription>
                </Field>
                <Field>
                    <FieldLabel htmlFor={`${id}-count`}>Number of keywords</FieldLabel>
                    <Select<number> value={form.count} onValueChange={(count) => count !== null && setForm({ count })}>
                        <SelectTrigger id={`${id}-count`}>
                            <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                            {KEYWORD_SUGGESTION_COUNTS.map((count) => (
                                <SelectItem key={count} value={count}>
                                    {String(count)}
                                </SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </Field>
            </div>
            <Field>
                <FieldLabel htmlFor={`${id}-description`}>What you do and who it is for</FieldLabel>
                <Textarea
                    id={`${id}-description`}
                    value={form.description}
                    onChange={(event) => setForm({ description: event.target.value })}
                    maxLength={aeoKeywordsSuggestBodyDescriptionMax}
                    rows={2}
                    placeholder="Open source product analytics for engineers at startups"
                />
                <FieldDescription>Optional. Read from the site when empty.</FieldDescription>
            </Field>
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
            <Text size="xs" variant="muted" render={<p className="m-0" />}>
                No new keywords came back. The ideas may already be on your list, or none were worth keeping. Add a
                description of what you do and try again.
            </Text>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Text size="xs" variant="muted" render={<span />}>
                    {/* translate="no" keeps the count updating when the browser translates the page. */}
                    <span translate="no">{selectedSuggestions.length}</span> of{' '}
                    {pluralize(suggestions.length, 'suggestion')} selected. Nothing is tracked until you add them.
                </Text>
                <Button
                    onClick={() => setSelectedKeywords(allSelected ? [] : suggestions.map(({ keyword }) => keyword))}
                >
                    {allSelected ? 'Select none' : 'Select all'}
                </Button>
            </div>
            <div>
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
                <Button
                    variant="outline"
                    onClick={editRequest}
                    disabledReason={adding ? 'Wait for the keywords to save' : undefined}
                >
                    Change inputs
                </Button>
                <Button
                    variant="primary"
                    onClick={addSelected}
                    loading={adding}
                    disabledReason={selectedSuggestions.length === 0 ? 'Select at least one keyword' : undefined}
                    data-attr="content-autopilot-keyword-suggest-add"
                >
                    {selectedSuggestions.length > 0
                        ? `Add ${pluralize(selectedSuggestions.length, 'keyword')}`
                        : 'Add keywords'}
                </Button>
            </>
        ) : view === 'pending' ? (
            <Button variant="outline" onClick={closeSuggest}>
                Close and keep working
            </Button>
        ) : view === 'failed' ? (
            <>
                <Button variant="outline" onClick={editRequest}>
                    Change inputs
                </Button>
                <Button
                    variant="primary"
                    onClick={startSuggestions}
                    loading={starting}
                    disabledReason={!siteDomain(form.domain) ? 'Change the inputs and enter your site' : undefined}
                >
                    Try again
                </Button>
            </>
        ) : (
            <>
                {job && job.status !== 'failed' ? (
                    <Button variant="outline" onClick={backToSuggestions}>
                        {job.status === 'pending' ? 'Back to progress' : 'Back to suggestions'}
                    </Button>
                ) : (
                    <Button variant="outline" onClick={closeSuggest}>
                        Cancel
                    </Button>
                )}
                <Button
                    variant="primary"
                    onClick={startSuggestions}
                    loading={starting}
                    disabledReason={!siteDomain(form.domain) ? 'Enter your site' : undefined}
                    data-attr="content-autopilot-keyword-suggest-start"
                >
                    Suggest keywords
                </Button>
            </>
        )

    return (
        // While the keywords save, the dialog stays open.
        <Credenza open={suggestOpen} onOpenChange={(next) => !next && !adding && closeSuggest()}>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle>Suggest keywords</CredenzaTitle>
                    <CredenzaDescription>
                        PostHog suggests keywords from your site, your prompts and the web searches the AI engines ran
                        while answering them. You pick which ones to track.
                    </CredenzaDescription>
                </CredenzaHeader>
                <CredenzaBody className="@container/suggest">
                    {view === 'pending' ? (
                        <div className="flex flex-col items-center gap-3 py-10 text-center">
                            <Spinner className="size-6" />
                            <Text size="xs" weight="semibold" render={<span />}>
                                Finding keywords for {domain}
                            </Text>
                            <Text size="xs" variant="muted" render={<p className="m-0 max-w-md" />}>
                                This usually takes a minute. You can close this and come back. The suggestions keep
                                loading in the background.
                            </Text>
                        </div>
                    ) : view === 'failed' ? (
                        <AiVisibilityBanner type="error">
                            {job?.error || "Couldn't suggest keywords. Try again."}
                        </AiVisibilityBanner>
                    ) : view === 'completed' ? (
                        <SuggestReview />
                    ) : (
                        <div className="flex flex-col gap-3">
                            {editingInputs && job?.status === 'completed' ? (
                                <AiVisibilityBanner type="info">
                                    Suggesting again replaces the {pluralize(job.suggestions.length, 'suggestion')} you
                                    have now.
                                </AiVisibilityBanner>
                            ) : null}
                            <SuggestForm />
                        </div>
                    )}
                </CredenzaBody>
                <CredenzaFooter>{footer}</CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
