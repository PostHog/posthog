import { useActions, useValues } from 'kea'
import { useEffect, memo } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { FeedbackPromptLogicProps, feedbackPromptLogic } from '../logics/feedbackPromptLogic'
import { FeedbackPromptRating as Rating } from '../utils/feedbackEvents'

/** The prompt's Good / Okay / Bad / Dismiss row, with 1 / 2 / 3 / x keyboard shortcuts while open. */
export const FeedbackPromptRating = memo(function FeedbackPromptRating(props: FeedbackPromptLogicProps): JSX.Element {
    const { isPromptVisible } = useValues(feedbackPromptLogic(props))
    const { submitRating } = useActions(feedbackPromptLogic(props))

    // Capture phase, so the shortcuts win over a focused composer.
    useEffect(() => {
        if (!isPromptVisible) {
            return
        }
        const keyToRating: Record<string, Rating> = { '1': 'good', '2': 'okay', '3': 'bad', x: 'dismissed' }
        const handleGlobalKeyDown = (e: KeyboardEvent): void => {
            const rating = keyToRating[e.key]
            if (rating) {
                e.preventDefault()
                e.stopPropagation()
                submitRating(rating)
            }
        }
        window.addEventListener('keydown', handleGlobalKeyDown, true)
        return () => window.removeEventListener('keydown', handleGlobalKeyDown, true)
    }, [isPromptVisible, submitRating])

    return (
        <div className="flex items-center gap-1">
            <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('good')}>
                Good <span className="text-muted ml-0.5">1</span>
            </LemonButton>
            <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('okay')}>
                Okay <span className="text-muted ml-0.5">2</span>
            </LemonButton>
            <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('bad')}>
                Bad <span className="text-muted ml-0.5">3</span>
            </LemonButton>
            <LemonButton size="xsmall" type="secondary" onClick={() => submitRating('dismissed')}>
                Dismiss <span className="text-muted ml-0.5">x</span>
            </LemonButton>
        </div>
    )
})
