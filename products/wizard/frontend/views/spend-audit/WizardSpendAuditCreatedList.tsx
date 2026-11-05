import { useActions, useValues } from 'kea'

import { IconTrash } from '@posthog/icons'
import { LemonButton, LemonCollapse, Link, Spinner } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import { createdObjectKey, wizardSpendAuditResultsLogic } from './wizardSpendAuditResultsLogic'
import type { WizardSpendAuditCreatedObject, WizardSpendAuditResultsLogicProps } from './wizardSpendAuditResultsLogic'

function CreatedObjectRow({
    object,
    deletingKey,
    onDelete,
}: {
    object: WizardSpendAuditCreatedObject
    deletingKey: string | null
    onDelete: (object: WizardSpendAuditCreatedObject) => void
}): JSX.Element {
    const key = createdObjectKey(object)
    return (
        <li className="flex min-w-0 items-center gap-2 text-xs ph-no-capture">
            <span className="w-16 shrink-0 text-muted">{object.kind === 'dashboard' ? 'Dashboard' : 'Insight'}</span>
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
                    icon={<IconTrash />}
                    tooltip="Delete"
                    aria-label="Delete"
                    loading={deletingKey === key}
                    disabledReason={deletingKey && deletingKey !== key ? 'Deleting another item' : undefined}
                    onClick={() => onDelete(object)}
                    data-attr="wizard-spend-audit-delete-created"
                />
            )}
        </li>
    )
}

export function WizardSpendAuditCreatedList(props: WizardSpendAuditResultsLogicProps): JSX.Element | null {
    const logic = wizardSpendAuditResultsLogic(props)
    const { createdObjects, deletingKey } = useValues(logic)
    const { deleteObject } = useActions(logic)

    const dashboardCount = props.notebook.dashboard_ids.length
    const insightCount = props.notebook.insight_ids.length
    if (dashboardCount + insightCount === 0) {
        return null
    }
    const summary = [
        dashboardCount > 0 && pluralize(dashboardCount, 'dashboard'),
        insightCount > 0 && pluralize(insightCount, 'insight'),
    ]
        .filter(Boolean)
        .join(' and ')

    return (
        <div className="border-t" data-attr="wizard-spend-audit-created">
            <LemonCollapse
                embedded
                size="small"
                defaultActiveKey="created"
                panels={[
                    {
                        key: 'created',
                        header: `Created in this project: ${summary}`,
                        className: 'px-0 py-2',
                        content: (
                            <div className="flex flex-col gap-2">
                                <p className="m-0 text-xs text-muted">
                                    The audit added these to help you get more from your data. Delete any you don't
                                    want.
                                </p>
                                {createdObjects === null ? (
                                    <Spinner />
                                ) : (
                                    <ul className="m-0 list-none space-y-1 p-0">
                                        {createdObjects.map((object) => (
                                            <CreatedObjectRow
                                                key={createdObjectKey(object)}
                                                object={object}
                                                deletingKey={deletingKey}
                                                onDelete={deleteObject}
                                            />
                                        ))}
                                    </ul>
                                )}
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
