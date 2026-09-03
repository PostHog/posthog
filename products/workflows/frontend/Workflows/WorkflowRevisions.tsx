import { useActions, useValues } from 'kea'

import { LemonButton, LemonTable, LemonTag } from '@posthog/lemon-ui'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import { AccessControlLevel, AccessControlResourceType } from '~/types'
import type { UserBasicType } from '~/types'

import type { HogFlowRevisionBasicApi } from '../generated/api.schemas'
import { workflowLogic } from './workflowLogic'
import { workflowRevisionsLogic } from './workflowRevisionsLogic'

export function WorkflowRevisions({ id }: { id: string }): JSX.Element {
    const logic = workflowRevisionsLogic({ id })
    const { revisions, revisionsCount, revisionsResponseLoading, restoringVersion } = useValues(logic)
    const { restoreRevision } = useActions(logic)
    const { originalWorkflow, workflowUserAccessLevel } = useValues(workflowLogic({ id }))

    const liveVersion = originalWorkflow?.version

    return (
        <div className="flex flex-col gap-2">
            <div>
                <h3 className="mb-0">Versions</h3>
                <p className="text-secondary mb-0">
                    A version is saved each time the live workflow changes. Restore one to open it as a draft, then
                    publish it to go live.
                </p>
            </div>
            <LemonTable<HogFlowRevisionBasicApi>
                dataSource={revisions}
                loading={revisionsResponseLoading}
                rowKey="version"
                footer={
                    revisionsCount > revisions.length ? (
                        <div className="px-3 py-2 text-xs text-secondary">
                            Showing the newest {revisions.length} of {revisionsCount} versions.
                        </div>
                    ) : undefined
                }
                emptyState="No versions yet. One is saved each time the live workflow changes."
                columns={[
                    {
                        title: 'Version',
                        key: 'version',
                        render: (_, revision) => (
                            <span className="flex items-center gap-2 font-semibold">
                                v{revision.version}
                                {revision.version === liveVersion && <LemonTag type="success">Live</LemonTag>}
                            </span>
                        ),
                    },
                    {
                        title: 'Changed by',
                        key: 'created_by',
                        render: (_, revision) =>
                            revision.created_by ? (
                                <span className="flex items-center gap-2">
                                    {/* The generated hedgehog_config shape differs from the app type in
                                        ways ProfilePicture never reads; the display fields match. */}
                                    <ProfilePicture user={revision.created_by as UserBasicType} size="md" showName />
                                </span>
                            ) : (
                                <span className="text-secondary">API or system</span>
                            ),
                    },
                    {
                        title: 'Date',
                        key: 'created_at',
                        render: (_, revision) => <TZLabel time={revision.created_at} />,
                    },
                    {
                        key: 'actions',
                        width: 0,
                        render: (_, revision) => (
                            // The flex wrapper keeps the button at its intrinsic height instead of
                            // stretching to the (avatar-driven) row height.
                            <div className="flex items-center">
                                <AccessControlAction
                                    resourceType={AccessControlResourceType.Workflow}
                                    minAccessLevel={AccessControlLevel.Editor}
                                    userAccessLevel={workflowUserAccessLevel ?? undefined}
                                >
                                    <LemonButton
                                        type="secondary"
                                        size="xsmall"
                                        className="whitespace-nowrap"
                                        onClick={() => restoreRevision(revision.version)}
                                        loading={restoringVersion === revision.version}
                                        disabledReason={
                                            revision.version === liveVersion
                                                ? 'This is the live version'
                                                : restoringVersion !== null && restoringVersion !== revision.version
                                                  ? 'Another restore is in progress'
                                                  : undefined
                                        }
                                    >
                                        Restore as draft
                                    </LemonButton>
                                </AccessControlAction>
                            </div>
                        ),
                    },
                ]}
            />
        </div>
    )
}
