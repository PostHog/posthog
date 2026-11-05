import { useActions, useValues } from 'kea'

import { LemonButton, LemonTag, Link, Spinner } from '@posthog/lemon-ui'

import { createdObjectKey, wizardSpendAuditResultsLogic } from './wizardSpendAuditResultsLogic'
import type { WizardSpendAuditResultsLogicProps } from './wizardSpendAuditResultsLogic'

export function WizardSpendAuditCreatedList(props: WizardSpendAuditResultsLogicProps): JSX.Element | null {
    const logic = wizardSpendAuditResultsLogic(props)
    const { createdObjects, createdObjectsLoading, deletingKey } = useValues(logic)
    const { deleteObject } = useActions(logic)

    if (createdObjectsLoading && createdObjects === null) {
        return <Spinner />
    }
    if (!createdObjects || createdObjects.length === 0) {
        return null
    }

    return (
        <div className="flex flex-col gap-1" data-attr="wizard-spend-audit-created">
            <div className="text-xs font-semibold">Created in this project</div>
            <p className="m-0 text-xs text-muted">
                The audit added these to help you get more from your data. Delete any you don't want.
            </p>
            <ul className="m-0 list-none space-y-1 p-0">
                {createdObjects.map((object) => {
                    const key = createdObjectKey(object)
                    return (
                        <li key={key} className="flex min-w-0 items-center gap-2 text-xs ph-no-capture">
                            <LemonTag size="small">{object.kind === 'dashboard' ? 'Dashboard' : 'Insight'}</LemonTag>
                            {object.deleted || !object.url ? (
                                <span className="min-w-0 flex-1 truncate text-muted">{object.name}</span>
                            ) : (
                                <Link to={object.url} className="min-w-0 flex-1 truncate">
                                    {object.name}
                                </Link>
                            )}
                            {object.deleted ? (
                                <span className="shrink-0 text-muted">Deleted</span>
                            ) : (
                                <LemonButton
                                    size="xsmall"
                                    status="danger"
                                    loading={deletingKey === key}
                                    disabledReason={
                                        deletingKey && deletingKey !== key ? 'Deleting another item' : undefined
                                    }
                                    onClick={() => deleteObject(object)}
                                    data-attr="wizard-spend-audit-delete-created"
                                >
                                    Delete
                                </LemonButton>
                            )}
                        </li>
                    )
                })}
            </ul>
        </div>
    )
}
