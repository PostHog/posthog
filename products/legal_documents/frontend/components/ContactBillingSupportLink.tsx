import { useActions } from 'kea'

import { Link } from '@posthog/lemon-ui'

import { supportLogic } from 'lib/components/Support/supportLogic'

export function ContactBillingSupportLink({
    children,
    'data-attr': dataAttr = 'legal-documents-contact-billing-support',
}: {
    children: React.ReactNode
    'data-attr'?: string
}): JSX.Element {
    const { openSupportForm } = useActions(supportLogic)
    return (
        <Link
            to=""
            onClick={() => openSupportForm({ billing_issue: true, isEmailFormOpen: true })}
            data-attr={dataAttr}
        >
            {children}
        </Link>
    )
}
