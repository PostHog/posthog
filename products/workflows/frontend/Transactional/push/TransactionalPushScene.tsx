import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { WorkflowInvocations } from '../../Workflows/WorkflowInvocations'
import { workflowLogic } from '../../Workflows/workflowLogic'
import { WorkflowMetrics } from '../../Workflows/WorkflowMetrics'
import { WorkflowRevisions } from '../../Workflows/WorkflowRevisions'
import { TransactionalPushApiExample } from './TransactionalPushApiExample'
import { TransactionalPushEditor } from './TransactionalPushEditor'
import { TransactionalPushLogicProps, transactionalPushLogic } from './transactionalPushLogic'

export const scene: SceneExport<TransactionalPushLogicProps> = {
    component: TransactionalPushScene,
    logic: transactionalPushLogic,
    paramsToProps: ({ params: { id } }): TransactionalPushLogicProps => ({ id }),
    productKey: ProductKey.WORKFLOWS,
}

export function TransactionalPushScene({ id }: TransactionalPushLogicProps): JSX.Element {
    const showPush = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_PUSH_API')
    const logic = transactionalPushLogic({ id })
    const {
        template,
        templateLoading,
        name,
        hasChanges,
        draftError,
        transactionalHogFlowId,
        tab,
        savedVariables,
        loadError,
    } = useValues(logic)
    const { setName, saveTemplate, discardChanges, setTab, makeTransactional, loadTemplate } = useActions(logic)

    if (!showPush) {
        return <NotFound object="page" />
    }
    if (loadError === 'not_found') {
        return (
            <NotFound
                object="push notification"
                caption="It may have been deleted, or it belongs to another project."
            />
        )
    }
    if (loadError === 'failed') {
        return (
            <SceneContent>
                <LemonBanner
                    type="error"
                    action={{
                        children: 'Try again',
                        onClick: loadTemplate,
                        'data-attr': 'transactional-push-retry-load',
                    }}
                >
                    This push notification couldn't load. Check your connection and try again.
                </LemonBanner>
            </SceneContent>
        )
    }
    if (template && template.type !== 'push') {
        return <NotFound object="push notification" caption="This template is an email, not a push notification." />
    }

    const editDisabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.Workflow, AccessControlLevel.Editor) ?? undefined
    const publishDisabledReason =
        editDisabledReason ??
        (templateLoading
            ? 'Loading'
            : !hasChanges
              ? 'No changes to publish'
              : !name.trim()
                ? 'Add a name'
                : (draftError ?? undefined))

    const tabs = (
        <LemonTabs
            activeKey={tab}
            onChange={setTab}
            tabs={[
                { key: 'content', label: 'Content', content: <TransactionalPushEditor id={id} /> },
                transactionalHogFlowId
                    ? { key: 'metrics', label: 'Metrics', content: <WorkflowMetrics id={transactionalHogFlowId} /> }
                    : null,
                transactionalHogFlowId
                    ? { key: 'sends', label: 'Sends', content: <WorkflowInvocations id={transactionalHogFlowId} /> }
                    : null,
                transactionalHogFlowId
                    ? {
                          key: 'versions',
                          label: 'Versions',
                          content: <WorkflowRevisions id={transactionalHogFlowId} />,
                      }
                    : null,
                {
                    key: 'api',
                    label: 'API',
                    content: transactionalHogFlowId ? (
                        <TransactionalPushApiExample templateId={id} variables={savedVariables} />
                    ) : (
                        <LemonBanner
                            type="info"
                            action={{
                                children: 'Make sendable',
                                onClick: makeTransactional,
                                disabledReason:
                                    editDisabledReason ?? (hasChanges ? 'Publish your changes first' : undefined),
                                'data-attr': 'transactional-push-make-transactional',
                            }}
                        >
                            This push notification can't be sent over the API yet.
                        </LemonBanner>
                    ),
                },
            ]}
        />
    )

    return (
        <SceneContent>
            <SceneTitleSection
                name={name}
                resourceType={{ type: 'transactional' }}
                canEdit={!editDisabledReason}
                isLoading={templateLoading && !template}
                onNameChange={setName}
                nameSuffix={
                    <LemonTag type="highlight" className="ml-1">
                        Push notification
                    </LemonTag>
                }
                actions={
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
                            disabledReason={publishDisabledReason}
                            data-attr="transactional-push-publish"
                        >
                            Publish
                        </LemonButton>
                    </>
                }
            />
            {!template ? null : transactionalHogFlowId ? (
                // The workflow tabs read workflowLogic without props, so it is bound to this push's workflow.
                <BindLogic logic={workflowLogic} props={{ id: transactionalHogFlowId }}>
                    {tabs}
                </BindLogic>
            ) : (
                tabs
            )}
        </SceneContent>
    )
}
