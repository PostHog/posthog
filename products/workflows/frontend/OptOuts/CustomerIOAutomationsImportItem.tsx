import { useActions } from 'kea'

import { IconArrowRight } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { customerioImportLogic } from '../Workflows/import/customerioImportLogic'
import { providerImportLogic } from './providerImportLogic'

export function CustomerIOAutomationsImportItem(): JSX.Element {
    const { closeImportModal } = useActions(providerImportLogic)
    const { openImportModal: openAutomationImport } = useActions(customerioImportLogic)

    return (
        <div>
            <Link
                className="flex items-center gap-2 font-semibold"
                onClick={() => {
                    closeImportModal()
                    openAutomationImport()
                }}
                // pinned: data-attr, autocapture and QA selectors use it
                data-attr="import-provider-customerio-automations"
            >
                <IconArrowRight className="text-base" />
                Automations, as draft workflows
            </Link>
            <div className="text-xs text-secondary ml-6">
                Opens its own import, through your AI agent or files from the Customer.io CLI. Drafts don't send until
                you enable them.
            </div>
        </div>
    )
}
