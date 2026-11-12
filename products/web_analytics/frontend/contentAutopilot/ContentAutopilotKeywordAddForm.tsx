import { useActions, useValues } from 'kea'

import { LemonButton, LemonTextArea } from '@posthog/lemon-ui'

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

    return (
        <div className="flex flex-col gap-2">
            <LemonTextArea
                value={keywordsDraft}
                onChange={setKeywordsDraft}
                onPressCmdEnter={() => !disabledReason && !addKeywordsSubmitting && addKeywords()}
                placeholder="session replay, feature flags, self-hosted analytics"
                minRows={2}
                maxRows={8}
                aria-label="Keywords to add"
                data-attr="content-autopilot-keywords-input"
            />
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-xs text-muted">
                    Separate keywords with commas or new lines. Matching ignores case.
                </span>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={addKeywords}
                    loading={addKeywordsSubmitting}
                    disabledReason={disabledReason}
                    data-attr="content-autopilot-keywords-add"
                >
                    {draftKeywords.length > 1 ? `Add ${draftKeywords.length} keywords` : 'Add keyword'}
                </LemonButton>
            </div>
        </div>
    )
}
