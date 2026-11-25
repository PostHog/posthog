import { useActions, useValues } from 'kea'

import { LemonModal, LemonSnack } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { ContentAutopilotKeywordAddForm } from './ContentAutopilotKeywordAddForm'
import { contentAutopilotKeywordsLogic } from './contentAutopilotKeywordsLogic'
import { MAX_KEYWORDS } from './keywordsReport'
import { QuillContentAutopilotKeywordsModal } from './QuillContentAutopilotKeywordsModal'

export const ContentAutopilotKeywordsModal = (): JSX.Element => {
    const { keywords, keywordsModalOpen, keywordRemoving } = useValues(contentAutopilotKeywordsLogic)
    const { removeKeyword, closeKeywordsModal } = useActions(contentAutopilotKeywordsLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')
    const title = `Keywords (${keywords?.length ?? 0} of ${MAX_KEYWORDS})`

    if (todayRailNav) {
        return (
            <QuillContentAutopilotKeywordsModal
                open={keywordsModalOpen}
                title={title}
                keywords={keywords ?? []}
                keywordRemoving={keywordRemoving}
                onRemove={removeKeyword}
                onClose={closeKeywordsModal}
            />
        )
    }

    return (
        <LemonModal isOpen={keywordsModalOpen} onClose={closeKeywordsModal} title={title} width={640}>
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
