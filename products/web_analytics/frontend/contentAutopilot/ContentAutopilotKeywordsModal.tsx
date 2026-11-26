import { useActions, useValues } from 'kea'

import { LemonModal, LemonSnack } from '@posthog/lemon-ui'

import { ContentAutopilotKeywordAddForm } from './ContentAutopilotKeywordAddForm'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { MAX_KEYWORDS } from './keywordsReport'

export const ContentAutopilotKeywordsModal = (): JSX.Element => {
    const { keywords, keywordsModalOpen, keywordRemoving } = useValues(contentAutopilotKeywordsLogic)
    const { removeKeyword, closeKeywordsModal } = useActions(contentAutopilotKeywordsLogic)

    return (
        <LemonModal
            isOpen={keywordsModalOpen}
            onClose={closeKeywordsModal}
            title={`Keywords (${keywords?.length ?? 0} of ${MAX_KEYWORDS})`}
            width={640}
        >
            <div className="flex flex-col gap-3" data-attr="content-autopilot-keywords-list">
                <div className="flex flex-wrap gap-1">
                    {(keywords ?? []).map((keyword) => (
                        <LemonSnack
                            key={keyword.id}
                            onClose={keywordRemoving[keyword.id] ? undefined : () => removeKeyword(keyword)}
                            className={keywordRemoving[keyword.id] ? 'opacity-50' : undefined}
                            data-attr="content-autopilot-keywords-remove"
                        >
                            {keyword.keyword}
                        </LemonSnack>
                    ))}
                </div>
                <ContentAutopilotKeywordAddForm />
            </div>
        </LemonModal>
    )
}
