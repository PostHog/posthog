import { useActions, useValues } from 'kea'

import { Button, Text, Textarea } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'

export const ContentAutopilotKeywordAddForm = (): JSX.Element => {
    const { keywordsDraft, draftKeywords, newDraftKeywords, keywordsLeft, addKeywordsSubmitting } =
        useValues(contentAutopilotKeywordsLogic)
    const { setKeywordsDraft, addKeywords } = useActions(contentAutopilotKeywordsLogic)

    const disabledReason =
        draftKeywords.length === 0
            ? 'Type or paste at least one keyword'
            : newDraftKeywords.length > keywordsLeft
              ? `You can add ${pluralize(keywordsLeft, 'more keyword')}`
              : undefined
    const submit = (): void => {
        if (!disabledReason && !addKeywordsSubmitting) {
            addKeywords()
        }
    }
    const submitLabel = draftKeywords.length > 1 ? `Add ${draftKeywords.length} keywords` : 'Add keyword'
    const hint = 'Separate keywords with commas or new lines. Matching ignores case.'

    return (
        <div className="flex flex-col gap-2">
            <Textarea
                value={keywordsDraft}
                onChange={(event) => setKeywordsDraft(event.target.value)}
                onKeyDown={(event) => {
                    if (event.key === 'Enter' && (event.metaKey || event.ctrlKey)) {
                        submit()
                    }
                }}
                placeholder="session replay, feature flags, self-hosted analytics"
                rows={2}
                aria-label="Keywords to add"
                data-attr="content-autopilot-keywords-input"
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
                <Text size="xs" variant="muted" render={<span />}>
                    {hint}
                </Text>
                <Button
                    variant="primary"
                    onClick={addKeywords}
                    loading={addKeywordsSubmitting}
                    disabledReason={disabledReason}
                    data-attr="content-autopilot-keywords-add"
                >
                    {submitLabel}
                </Button>
            </div>
        </div>
    )
}
