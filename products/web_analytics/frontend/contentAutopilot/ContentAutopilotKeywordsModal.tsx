import { useActions, useValues } from 'kea'

import { Chip, ChipClose, Credenza, CredenzaBody, CredenzaContent, CredenzaHeader, CredenzaTitle } from '@posthog/quill'

import { ContentAutopilotKeywordAddForm } from './ContentAutopilotKeywordAddForm'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { MAX_KEYWORDS } from './keywordsReport'

export const ContentAutopilotKeywordsModal = (): JSX.Element => {
    const { keywords, keywordsModalOpen, keywordRemoving } = useValues(contentAutopilotKeywordsLogic)
    const { removeKeyword, closeKeywordsModal } = useActions(contentAutopilotKeywordsLogic)

    return (
        <Credenza open={keywordsModalOpen} onOpenChange={(next) => !next && closeKeywordsModal()}>
            <CredenzaContent>
                <CredenzaHeader>
                    <CredenzaTitle>{`Keywords (${keywords?.length ?? 0} of ${MAX_KEYWORDS})`}</CredenzaTitle>
                </CredenzaHeader>
                <CredenzaBody className="flex flex-col gap-3" data-attr="content-autopilot-keywords-list">
                    <div className="flex flex-wrap gap-1">
                        {(keywords ?? []).map((keyword) => (
                            <Chip
                                key={keyword.id}
                                className={keywordRemoving[keyword.id] ? 'opacity-50' : undefined}
                                data-attr="content-autopilot-keywords-remove"
                            >
                                {keyword.keyword}
                                <ChipClose
                                    aria-label={`Remove ${keyword.keyword}`}
                                    onClick={() => removeKeyword(keyword)}
                                    disabledReason={keywordRemoving[keyword.id] ? 'Removing the keyword' : undefined}
                                />
                            </Chip>
                        ))}
                    </div>
                    <ContentAutopilotKeywordAddForm />
                </CredenzaBody>
            </CredenzaContent>
        </Credenza>
    )
}
