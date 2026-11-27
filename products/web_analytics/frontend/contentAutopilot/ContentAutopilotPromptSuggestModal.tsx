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
    Empty,
    EmptyDescription,
    EmptyHeader,
    EmptyTitle,
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

import { TagsCombobox } from 'lib/components/Scenes/TagsCombobox'
import { pluralize } from 'lib/utils/strings'

import type {
    AEOPromptSuggestionApi,
    FunnelStageEnumApi,
    PromptCircleEnumApi,
} from 'products/web_analytics/frontend/generated/api.schemas'
import {
    aeoPromptsSuggestBodyBrandMax,
    aeoPromptsSuggestBodyCompetitorsItemMax,
    aeoPromptsSuggestBodyCompetitorsMax,
    aeoPromptsSuggestBodyDescriptionMax,
    aeoPromptsSuggestBodyDomainMax,
} from 'products/web_analytics/frontend/generated/api.zod'

import { AiVisibilityBanner } from './AiVisibilityBanner'
import { AiVisibilityTag } from './AiVisibilityTag'
import {
    SUGGESTION_COUNTS,
    contentAutopilotPromptSuggestionsLogic,
    siteDomain,
} from './contentAutopilotPromptSuggestionsLogic'

const CIRCLES: Record<PromptCircleEnumApi, { label: string; description: string }> = {
    differentiation: {
        label: 'Differentiation',
        description: 'A need your buyers have that you meet and competitors do not.',
    },
    battleground: { label: 'Battleground', description: 'A need you and your competitors all meet.' },
    vulnerability: { label: 'Vulnerability', description: 'A need competitors meet better than you do.' },
    table_stakes: { label: 'Table stakes', description: 'Something every tool in the category does.' },
    branded: { label: 'Branded', description: 'Names your brand. Checks how assistants describe you.' },
}

const STAGES: Record<FunnelStageEnumApi, string> = {
    top: 'Learning',
    middle: 'Comparing',
    bottom: 'Choosing',
}

const SuggestionRow = ({ suggestion }: { suggestion: AEOPromptSuggestionApi }): JSX.Element => {
    const { selectedPrompts } = useValues(contentAutopilotPromptSuggestionsLogic)
    const { toggleSuggestion } = useActions(contentAutopilotPromptSuggestionsLogic)
    const circle = CIRCLES[suggestion.circle]

    return (
        <div className="flex gap-2 border-b py-2 last:border-b-0">
            <Checkbox
                checked={selectedPrompts.includes(suggestion.prompt)}
                onCheckedChange={() => toggleSuggestion(suggestion.prompt)}
                aria-label={`Select ${suggestion.prompt}`}
                className="mt-0.5"
            />
            <div className="flex min-w-0 flex-col gap-1">
                <Text size="xs" weight="semibold" className="m-0 break-words">
                    {suggestion.prompt}
                </Text>
                <div className="flex flex-wrap items-center gap-1">
                    {suggestion.topic ? <AiVisibilityTag>{suggestion.topic}</AiVisibilityTag> : null}
                    <Tooltip>
                        <TooltipTrigger render={<span tabIndex={0} className="inline-flex" />}>
                            <AiVisibilityTag type={suggestion.branded ? 'muted' : 'highlight'}>
                                {circle.label}
                            </AiVisibilityTag>
                        </TooltipTrigger>
                        <TooltipContent>{circle.description}</TooltipContent>
                    </Tooltip>
                    <AiVisibilityTag type="muted">{STAGES[suggestion.funnel_stage]}</AiVisibilityTag>
                </div>
                {suggestion.reason ? (
                    <Text size="xs" variant="muted" className="m-0">
                        {suggestion.reason}
                    </Text>
                ) : null}
            </div>
        </div>
    )
}

// The API takes at most 20 entries of 200 characters each.
const SuggestedCompetitors = (): JSX.Element | null => {
    const { job, selectedCompetitors } = useValues(contentAutopilotPromptSuggestionsLogic)
    const { toggleCompetitor } = useActions(contentAutopilotPromptSuggestionsLogic)
    const competitors = (job?.competitors ?? []).filter(({ domain }) => !!domain)
    if (competitors.length === 0) {
        return null
    }
    return (
        <div className="flex flex-col gap-2 rounded-md border p-3" data-attr="content-autopilot-suggest-competitors">
            <div>
                <Text size="sm" weight="semibold" render={<span className="m-0" />}>
                    Competitors
                </Text>
                <Text size="xs" variant="muted" render={<p className="m-0" />}>
                    Rankings compares you against the ones you keep ticked. You can change them later in settings.
                </Text>
            </div>
            <div className="flex flex-wrap gap-x-4 gap-y-1">
                {competitors.map(({ name, domain }) => (
                    <label key={domain} className="flex cursor-pointer items-center gap-2">
                        <Checkbox
                            checked={selectedCompetitors.includes(domain)}
                            onCheckedChange={() => toggleCompetitor(domain)}
                            data-attr="content-autopilot-suggest-competitor"
                        />
                        <Text size="sm" render={<span className="m-0" />}>{`${name} (${domain})`}</Text>
                    </label>
                ))}
            </div>
        </div>
    )
}

const cappedList = (values: string[]): string[] =>
    values
        .slice(0, aeoPromptsSuggestBodyCompetitorsMax)
        .map((value) => value.slice(0, aeoPromptsSuggestBodyCompetitorsItemMax))

const SuggestForm = (): JSX.Element => {
    const { form, startError } = useValues(contentAutopilotPromptSuggestionsLogic)
    const { setForm } = useActions(contentAutopilotPromptSuggestionsLogic)
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
                    maxLength={aeoPromptsSuggestBodyDomainMax}
                    placeholder="example.com"
                    autoFocus
                    data-attr="content-autopilot-suggest-domain"
                />
                <FieldDescription>
                    PostHog reads this site to understand what you do and who it is for.
                </FieldDescription>
            </Field>
            <div className="grid grid-cols-1 gap-4 @md/suggest:grid-cols-2">
                <Field>
                    <FieldLabel htmlFor={`${id}-brand`}>Brand</FieldLabel>
                    <Input
                        id={`${id}-brand`}
                        value={form.brand}
                        onChange={(event) => setForm({ brand: event.target.value })}
                        maxLength={aeoPromptsSuggestBodyBrandMax}
                    />
                    <FieldDescription>Optional. Read from the site when empty.</FieldDescription>
                </Field>
                <Field>
                    <FieldLabel htmlFor={`${id}-count`}>Number of prompts</FieldLabel>
                    <Select<number> value={form.count} onValueChange={(count) => count !== null && setForm({ count })}>
                        <SelectTrigger id={`${id}-count`}>
                            <SelectValue>{(count: number | null) => count}</SelectValue>
                        </SelectTrigger>
                        <SelectContent>
                            {SUGGESTION_COUNTS.map((count) => (
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
                    maxLength={aeoPromptsSuggestBodyDescriptionMax}
                    rows={2}
                    placeholder="For example: scheduling software for dental clinics"
                />
                <FieldDescription>Optional. Read from the site when empty.</FieldDescription>
            </Field>
            <Field>
                <FieldLabel htmlFor={`${id}-competitors`}>Competitors</FieldLabel>
                <TagsCombobox
                    id={`${id}-competitors`}
                    value={form.competitors}
                    onChange={(competitors) => setForm({ competitors: cappedList(competitors) })}
                    placeholder="Add a name or domain"
                    customValueNoun="competitor"
                />
                <FieldDescription>Optional. PostHog picks the main ones when empty.</FieldDescription>
            </Field>
            <Field>
                <FieldLabel htmlFor={`${id}-topics`}>Topics</FieldLabel>
                <TagsCombobox
                    id={`${id}-topics`}
                    value={form.topics}
                    onChange={(topics) => setForm({ topics: cappedList(topics) })}
                    placeholder="Add a topic"
                    customValueNoun="topic"
                />
                <FieldDescription>Optional. PostHog picks 3 to 6 when empty.</FieldDescription>
            </Field>
        </div>
    )
}

const SuggestReview = (): JSX.Element => {
    const { job, selectedSuggestions, adding } = useValues(contentAutopilotPromptSuggestionsLogic)
    const { setSelectedPrompts, editRequest } = useActions(contentAutopilotPromptSuggestionsLogic)
    const suggestions = job?.suggestions ?? []
    const allSelected = selectedSuggestions.length === suggestions.length

    if (suggestions.length === 0) {
        return (
            <Empty className="py-6">
                <EmptyHeader>
                    <EmptyTitle>No new prompts came back</EmptyTitle>
                    <EmptyDescription>
                        The ideas may already be tracked, or none were worth keeping. Change the topics or competitors
                        and try again.
                    </EmptyDescription>
                </EmptyHeader>
            </Empty>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Text size="xs" variant="muted" className="m-0">
                    {/* translate="no" keeps the count updating when the browser translates the page. */}
                    <span translate="no">{selectedSuggestions.length}</span> of{' '}
                    {pluralize(suggestions.length, 'suggestion')} selected. Nothing is tracked until you add them.
                </Text>
                <div className="flex items-center gap-1">
                    <Button
                        onClick={() => setSelectedPrompts(allSelected ? [] : suggestions.map(({ prompt }) => prompt))}
                    >
                        {allSelected ? 'Select none' : 'Select all'}
                    </Button>
                    <Button onClick={editRequest} disabledReason={adding ? 'Wait for the prompts to save' : undefined}>
                        Change inputs
                    </Button>
                </div>
            </div>
            <div>
                {suggestions.map((suggestion) => (
                    <SuggestionRow key={suggestion.prompt} suggestion={suggestion} />
                ))}
            </div>
            <SuggestedCompetitors />
        </div>
    )
}

type SuggestView = 'form' | 'loading' | 'pending' | 'failed' | 'completed'

export const ContentAutopilotPromptSuggestModal = (): JSX.Element => {
    const { suggestOpen, form, job, jobRef, starting, adding, selectedSuggestions, editingInputs } = useValues(
        contentAutopilotPromptSuggestionsLogic
    )
    const { closeSuggest, startSuggestions, editRequest, backToSuggestions, addSelected } = useActions(
        contentAutopilotPromptSuggestionsLogic
    )
    // A job saved from an earlier visit is fetched again on mount, so it shows as loading rather than the empty form.
    // A cancelled job left nothing to review, so it opens the form again.
    const view: SuggestView =
        editingInputs || job?.status === 'cancelled' ? 'form' : job ? job.status : jobRef ? 'loading' : 'form'
    const domain = jobRef?.domain || siteDomain(form.domain) || 'your site'
    const noSiteReason = !siteDomain(form.domain) ? 'Enter your site' : undefined
    const noSuggestions = view === 'completed' && (job?.suggestions.length ?? 0) === 0

    const footer =
        view === 'completed' ? (
            <>
                <Button
                    variant="outline"
                    onClick={closeSuggest}
                    disabledReason={adding ? 'Wait for the prompts to save' : undefined}
                >
                    Cancel
                </Button>
                {noSuggestions ? (
                    <Button variant="primary" onClick={editRequest}>
                        Change inputs
                    </Button>
                ) : (
                    <Button
                        variant="primary"
                        onClick={addSelected}
                        loading={adding}
                        disabledReason={selectedSuggestions.length === 0 ? 'Select at least one prompt' : undefined}
                        data-attr="content-autopilot-suggest-add"
                    >
                        {selectedSuggestions.length > 0
                            ? `Add ${pluralize(selectedSuggestions.length, 'prompt')}`
                            : 'Add prompts'}
                    </Button>
                )}
            </>
        ) : view === 'pending' || view === 'loading' ? (
            <Button variant="outline" onClick={closeSuggest}>
                Close and keep working
            </Button>
        ) : view === 'failed' ? (
            <>
                <Button variant="outline" onClick={editRequest}>
                    Change inputs
                </Button>
                <Button variant="primary" onClick={startSuggestions} loading={starting} disabledReason={noSiteReason}>
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
                    disabledReason={noSiteReason}
                    data-attr="content-autopilot-suggest-start"
                >
                    Suggest prompts
                </Button>
            </>
        )

    return (
        // While the prompts save, the dialog stays open.
        <Credenza open={suggestOpen} onOpenChange={(next) => !next && !adding && closeSuggest()}>
            <CredenzaContent className="sm:max-w-180">
                <CredenzaHeader>
                    <CredenzaTitle>Suggest prompts</CredenzaTitle>
                    <CredenzaDescription>
                        PostHog reads your site and writes questions your buyers would ask an AI assistant. You pick
                        which ones to track.
                    </CredenzaDescription>
                </CredenzaHeader>
                <CredenzaBody className="@container/suggest">
                    {view === 'loading' ? (
                        <div role="status" className="flex flex-col items-center gap-3 py-10 text-center">
                            <Spinner />
                            <Text size="xs" variant="muted" className="m-0">
                                Loading your suggestions
                            </Text>
                        </div>
                    ) : view === 'pending' ? (
                        <div role="status" className="flex flex-col items-center gap-3 py-10 text-center">
                            <Spinner />
                            <Text size="xs" weight="semibold" className="m-0">
                                Reading {domain} and writing prompts
                            </Text>
                            <Text size="xs" variant="muted" className="m-0 max-w-md">
                                This usually takes a minute or two. You can close this and come back. The suggestions
                                keep loading in the background.
                            </Text>
                        </div>
                    ) : view === 'failed' ? (
                        <AiVisibilityBanner type="error">
                            {job?.error || "Couldn't suggest prompts. Try again."}
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
