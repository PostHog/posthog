import { useActions, useValues } from 'kea'

import { LemonBanner } from '@posthog/lemon-ui'

import { transactionalTemplatesLogic } from './transactionalTemplatesLogic'

export function TransactionalTemplatesLoadError({
    message,
    dataAttr,
}: {
    message: string
    dataAttr: string
}): JSX.Element | null {
    const { transactionalTemplatesFailed } = useValues(transactionalTemplatesLogic)
    const { loadTransactionalTemplates } = useActions(transactionalTemplatesLogic)

    if (!transactionalTemplatesFailed) {
        return null
    }
    return (
        <LemonBanner
            type="error"
            action={{ children: 'Try again', onClick: () => loadTransactionalTemplates(), 'data-attr': dataAttr }}
        >
            {message}
        </LemonBanner>
    )
}
