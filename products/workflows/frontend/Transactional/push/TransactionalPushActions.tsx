import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { transactionalPushLogic } from './transactionalPushLogic'

export function TransactionalPushActions({
    id,
    editDisabledReason,
}: {
    id: string
    editDisabledReason: string | undefined
}): JSX.Element {
    const { template, templateLoading, hasChanges, publishBlockedReason } = useValues(transactionalPushLogic({ id }))
    const { saveTemplate, discardChanges } = useActions(transactionalPushLogic({ id }))

    return (
        <>
            {hasChanges ? (
                <LemonButton
                    type="secondary"
                    size="small"
                    onClick={discardChanges}
                    data-attr="transactional-push-discard"
                >
                    Discard changes
                </LemonButton>
            ) : null}
            <LemonButton
                type="primary"
                size="small"
                onClick={saveTemplate}
                loading={templateLoading && !!template}
                disabledReason={editDisabledReason ?? publishBlockedReason ?? undefined}
                data-attr="transactional-push-publish"
            >
                Publish
            </LemonButton>
        </>
    )
}
