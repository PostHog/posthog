import { useActions, useValues } from 'kea'

import {
    LemonBanner,
    LemonButton,
    LemonCheckbox,
    LemonInput,
    LemonInputSelect,
    LemonModal,
    LemonSelect,
    LemonTag,
    LemonTextArea,
    Spinner,
    Tooltip,
} from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { pluralize } from 'lib/utils/strings'

import type {
    AEOPromptSuggestionApi,
    FunnelStageEnumApi,
    PromptCircleEnumApi,
} from 'products/web_analytics/frontend/generated/api.schemas'

import { SUGGESTION_COUNTS, contentAutopilotPromptSuggestionsLogic } from './contentAutopilotPromptSuggestionsLogic'

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
        <div className="flex gap-2 py-2 border-b last:border-b-0">
            <LemonCheckbox
                checked={selectedPrompts.includes(suggestion.prompt)}
                onChange={() => toggleSuggestion(suggestion.prompt)}
                aria-label={`Select ${suggestion.prompt}`}
            />
            <div className="flex flex-col gap-1 min-w-0">
                <span className="font-semibold break-words">{suggestion.prompt}</span>
                <div className="flex flex-wrap items-center gap-1">
                    {suggestion.topic ? <LemonTag>{suggestion.topic}</LemonTag> : null}
                    <Tooltip title={circle.description}>
                        <LemonTag type={suggestion.branded ? 'muted' : 'highlight'}>{circle.label}</LemonTag>
                    </Tooltip>
                    <LemonTag type="muted">{STAGES[suggestion.funnel_stage]}</LemonTag>
                </div>
                {suggestion.reason ? <span className="text-xs text-muted">{suggestion.reason}</span> : null}
            </div>
        </div>
    )
}

const SuggestForm = (): JSX.Element => {
    const { form, startError } = useValues(contentAutopilotPromptSuggestionsLogic)
    const { setForm } = useActions(contentAutopilotPromptSuggestionsLogic)

    return (
        <div className="flex flex-col gap-4">
            {startError ? <LemonBanner type="error">{startError}</LemonBanner> : null}
            <LemonField.Pure label="Site" help="Claude reads this site to understand what you do and who it is for.">
                <LemonInput
                    value={form.domain}
                    onChange={(domain) => setForm({ domain })}
                    placeholder="example.com"
                    autoFocus
                    data-attr="content-autopilot-suggest-domain"
                />
            </LemonField.Pure>
            <div className="grid grid-cols-1 @md/suggest:grid-cols-2 gap-4">
                <LemonField.Pure label="Brand" help="Optional. Read from the site when empty.">
                    <LemonInput value={form.brand} onChange={(brand) => setForm({ brand })} />
                </LemonField.Pure>
                <LemonField.Pure label="Number of prompts">
                    <LemonSelect
                        value={form.count}
                        onChange={(count) => setForm({ count })}
                        options={SUGGESTION_COUNTS.map((count) => ({ value: count, label: String(count) }))}
                    />
                </LemonField.Pure>
            </div>
            <LemonField.Pure label="What you do and who it is for" help="Optional. Read from the site when empty.">
                <LemonTextArea
                    value={form.description}
                    onChange={(description) => setForm({ description })}
                    minRows={2}
                    placeholder="Open source product analytics for engineers at startups"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Competitors" help="Optional. Claude picks the main ones when empty.">
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={form.competitors}
                    onChange={(competitors) => setForm({ competitors })}
                    placeholder="Add a name or domain"
                />
            </LemonField.Pure>
            <LemonField.Pure label="Topics" help="Optional. Claude picks 3 to 6 when empty.">
                <LemonInputSelect
                    mode="multiple"
                    allowCustomValues
                    value={form.topics}
                    onChange={(topics) => setForm({ topics })}
                    placeholder="Add a topic"
                />
            </LemonField.Pure>
        </div>
    )
}

const SuggestReview = (): JSX.Element => {
    const { job, selectedPrompts } = useValues(contentAutopilotPromptSuggestionsLogic)
    const { setSelectedPrompts } = useActions(contentAutopilotPromptSuggestionsLogic)
    const suggestions = job?.suggestions ?? []

    if (suggestions.length === 0) {
        return (
            <p className="m-0 text-muted">
                No new prompts this time. Everything Claude came up with is already in your prompt set. Change the
                topics or competitors and try again.
            </p>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
                <span className="text-muted">
                    {selectedPrompts.length} of {pluralize(suggestions.length, 'suggestion')} selected. Nothing is
                    tracked until you add them.
                </span>
                <LemonButton
                    size="small"
                    type="tertiary"
                    onClick={() =>
                        setSelectedPrompts(
                            selectedPrompts.length === suggestions.length ? [] : suggestions.map(({ prompt }) => prompt)
                        )
                    }
                >
                    {selectedPrompts.length === suggestions.length ? 'Select none' : 'Select all'}
                </LemonButton>
            </div>
            <div className="max-h-[50vh] overflow-y-auto">
                {suggestions.map((suggestion) => (
                    <SuggestionRow key={suggestion.prompt} suggestion={suggestion} />
                ))}
            </div>
        </div>
    )
}

export const ContentAutopilotPromptSuggestModal = (): JSX.Element => {
    const { suggestOpen, form, job, starting, adding, selectedSuggestions } = useValues(
        contentAutopilotPromptSuggestionsLogic
    )
    const { closeSuggest, startSuggestions, editRequest, addSelected } = useActions(
        contentAutopilotPromptSuggestionsLogic
    )
    const status = job?.status

    const footer =
        status === 'completed' ? (
            <>
                <LemonButton
                    type="secondary"
                    onClick={editRequest}
                    disabledReason={adding ? 'Wait for the prompts to save' : undefined}
                >
                    Change inputs
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={addSelected}
                    loading={adding}
                    disabledReason={selectedSuggestions.length === 0 ? 'Select at least one prompt' : undefined}
                    data-attr="content-autopilot-suggest-add"
                >
                    {selectedSuggestions.length > 0
                        ? `Add ${pluralize(selectedSuggestions.length, 'prompt')}`
                        : 'Add prompts'}
                </LemonButton>
            </>
        ) : status === 'pending' ? (
            <LemonButton type="secondary" onClick={closeSuggest}>
                Close and keep working
            </LemonButton>
        ) : status === 'failed' ? (
            <LemonButton type="primary" onClick={editRequest}>
                Try again
            </LemonButton>
        ) : (
            <>
                <LemonButton type="secondary" onClick={closeSuggest}>
                    Cancel
                </LemonButton>
                <LemonButton
                    type="primary"
                    onClick={startSuggestions}
                    loading={starting}
                    disabledReason={!form.domain.trim() ? 'Enter your site' : undefined}
                    data-attr="content-autopilot-suggest-start"
                >
                    Suggest prompts
                </LemonButton>
            </>
        )

    return (
        <LemonModal
            isOpen={suggestOpen}
            onClose={closeSuggest}
            title="Suggest prompts"
            description="Claude reads your site and writes questions your buyers would ask an AI assistant. You pick which ones to track."
            width={720}
            footer={footer}
        >
            <div className="@container/suggest">
                {status === 'pending' ? (
                    <div className="flex flex-col items-center gap-3 py-10 text-center">
                        <Spinner className="text-2xl" />
                        <span className="font-semibold">Reading {form.domain} and writing prompts</span>
                        <span className="text-muted max-w-md">
                            This usually takes a minute or two. You can close this and come back. The suggestions keep
                            loading in the background.
                        </span>
                    </div>
                ) : status === 'failed' ? (
                    <LemonBanner type="error">{job?.error || "Couldn't suggest prompts. Try again."}</LemonBanner>
                ) : status === 'completed' ? (
                    <SuggestReview />
                ) : (
                    <SuggestForm />
                )}
            </div>
        </LemonModal>
    )
}
