import { useActions, useValues } from 'kea'

import {
    Button,
    Chip,
    ChipClose,
    Credenza,
    CredenzaBody,
    CredenzaContent,
    CredenzaFooter,
    CredenzaHeader,
    CredenzaTitle,
    Text,
} from '@posthog/quill'

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
                    {keywords?.length ? (
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
                                        onClick={() => removeKeyword(keyword)}
                                        disabledReason={
                                            keywordRemoving[keyword.id] ? 'Removing the keyword' : undefined
                                        }
                                    />
                                </Chip>
                            ))}
                        </div>
                    ) : (
                        <Text size="xs" variant="muted" render={<p className="m-0" />}>
                            No keywords yet. Add the words and phrases you want to be known for.
                        </Text>
                    )}
                    <ContentAutopilotKeywordAddForm />
                </CredenzaBody>
                {/* The drawer on a phone has no close button of its own. */}
                <CredenzaFooter>
                    <Button variant="outline" onClick={closeKeywordsModal}>
                        Done
                    </Button>
                </CredenzaFooter>
            </CredenzaContent>
        </Credenza>
    )
}
