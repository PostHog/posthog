import { useActions, useValues } from 'kea'

import { Button, Field, FieldDescription, Textarea } from '@posthog/quill'

import { pluralize } from 'lib/utils/strings'

import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { MAX_KEYWORDS } from './keywordsReport'

export const ContentAutopilotKeywordAddForm = (): JSX.Element => {
    const { keywordsDraft, draftKeywords, newDraftKeywords, keywordsLeft, addKeywordsSubmitting } =
        useValues(contentAutopilotKeywordsLogic)
    const { setKeywordsDraft, addKeywords } = useActions(contentAutopilotKeywordsLogic)

    const disabledReason =
        keywordsLeft <= 0
            ? `You track ${MAX_KEYWORDS} keywords, the most allowed. Remove one to add another.`
            : draftKeywords.length === 0
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
            <Field>
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
                <FieldDescription>{hint}</FieldDescription>
            </Field>
            <div className="flex justify-end">
                <Button
                    variant="primary"
                    onClick={submit}
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
