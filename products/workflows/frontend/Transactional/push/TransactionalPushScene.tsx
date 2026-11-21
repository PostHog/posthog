import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTag } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { TransactionalPushActions } from './TransactionalPushActions'
import { TransactionalPushLogicProps, transactionalPushLogic } from './transactionalPushLogic'
import { TransactionalPushTabs } from './TransactionalPushTabs'

export const scene: SceneExport<TransactionalPushLogicProps> = {
    component: TransactionalPushScene,
    logic: transactionalPushLogic,
    paramsToProps: ({ params: { id } }): TransactionalPushLogicProps => ({ id }),
    productKey: ProductKey.WORKFLOWS,
}

export function TransactionalPushScene({ id }: TransactionalPushLogicProps): JSX.Element {
    const showPush = useFeatureFlag('WORKFLOWS_TRANSACTIONAL_PUSH_API')
    const logic = transactionalPushLogic({ id })
    const { template, templateLoading, name, loadError } = useValues(logic)
    const { setName, loadTemplate } = useActions(logic)

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
                actions={<TransactionalPushActions id={id} editDisabledReason={editDisabledReason} />}
            />
            {template ? <TransactionalPushTabs id={id} editDisabledReason={editDisabledReason} /> : null}
        </SceneContent>
    )
}
