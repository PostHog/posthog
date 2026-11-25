import { Chip, ChipClose, Credenza, CredenzaBody, CredenzaContent, CredenzaHeader, CredenzaTitle } from '@posthog/quill'

import type { AEOKeywordApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { ContentAutopilotKeywordAddForm } from './ContentAutopilotKeywordAddForm'

export const QuillContentAutopilotKeywordsModal = ({
    open,
    title,
    keywords,
    keywordRemoving,
    onRemove,
    onClose,
}: {
    open: boolean
    title: string
    keywords: AEOKeywordApi[]
    keywordRemoving: Record<string, boolean>
    onRemove: (keyword: AEOKeywordApi) => void
    onClose: () => void
}): JSX.Element => (
    <Credenza open={open} onOpenChange={(next) => !next && onClose()}>
        <CredenzaContent>
            <CredenzaHeader>
                <CredenzaTitle>{title}</CredenzaTitle>
            </CredenzaHeader>
            <CredenzaBody className="flex flex-col gap-3" data-attr="content-autopilot-keywords-list">
                <div className="flex flex-wrap gap-1">
                    {keywords.map((keyword) => (
                        <Chip
                            key={keyword.id}
                            className={keywordRemoving[keyword.id] ? 'opacity-50' : undefined}
                            data-attr="content-autopilot-keywords-remove"
                        >
                            {keyword.keyword}
                            <ChipClose
                                aria-label={`Remove ${keyword.keyword}`}
                                onClick={() => onRemove(keyword)}
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
