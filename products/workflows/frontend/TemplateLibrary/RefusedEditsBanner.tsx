import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { MessageTemplateLogicProps, messageTemplateLogic } from './messageTemplateLogic'

export const DUPLICATE_REFUSED_EDITS_REASON = 'To keep your changes, use "Duplicate with my changes"'

export function RefusedEditsBanner(props: MessageTemplateLogicProps): JSX.Element | null {
    const logic = messageTemplateLogic(props)
    const { refusedEdits, isDuplicating } = useValues(logic)
    const { duplicateWithMyChanges, setRefusedEdits } = useActions(logic)

    if (!refusedEdits) {
        return null
    }

    return (
        <LemonBanner
            type="warning"
            className="shrink-0"
            onClose={() => setRefusedEdits(null)}
            action={{
                children: 'Duplicate with my changes',
                onClick: duplicateWithMyChanges,
                loading: isDuplicating,
                'data-attr': 'message-template-refused-edits-duplicate',
            }}
        >
            Your changes weren't saved. While you were editing, an upload from code took this template back. To keep
            your changes, duplicate the template with them. If you close this message, your changes are discarded.
        </LemonBanner>
    )
}
