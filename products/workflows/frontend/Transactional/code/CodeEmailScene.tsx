import { BindLogic, useActions, useValues } from 'kea'

import { IconInfo, IconLock } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { WorkflowInvocations } from '../../Workflows/WorkflowInvocations'
import { workflowLogic } from '../../Workflows/workflowLogic'
import { WorkflowMetrics } from '../../Workflows/WorkflowMetrics'
import { CodeBadge } from './CodeBadge'
import { CodeEmailApiExample } from './CodeEmailApiExample'
import { CodeEmailLogicProps, codeEmailLogic } from './codeEmailLogic'

export const scene: SceneExport<CodeEmailLogicProps> = {
    component: CodeEmailScene,
    logic: codeEmailLogic,
    paramsToProps: ({ params: { id } }): CodeEmailLogicProps => ({ id }),
    productKey: ProductKey.WORKFLOWS,
}

export function CodeEmailScene(): JSX.Element {
    // The scene binds the logic to the email ID in the URL.
    const { codeEmail, loadState, saving, tab, editDisabledReason } = useValues(codeEmailLogic)
    const { loadCodeEmail, updateCodeEmail, setTab, showSends } = useActions(codeEmailLogic)

    if (loadState === 'not-found') {
        return (
            <NotFound
                object="email"
                caption="No email your code sends in this project has this ID. It may have moved to a template."
            />
        )
    }
    if (loadState === 'failed') {
        return (
            <SceneContent>
                <LemonBanner
                    type="error"
                    action={{ children: 'Try again', onClick: () => loadCodeEmail(), 'data-attr': 'code-email-retry' }}
                >
                    This email couldn't load. Check your connection and try again.
                </LemonBanner>
            </SceneContent>
        )
    }

    return (
        <SceneContent data-attr="code-email-scene">
            <div className="flex flex-col gap-2">
                <SceneTitleSection
                    name={codeEmail?.key}
                    description={codeEmail?.description ?? null}
                    resourceType={{ type: 'transactional' }}
                    isLoading={!codeEmail}
                    canEdit={!editDisabledReason}
                    descriptionAlwaysVisible
                    saveOnBlur
                    renameDebounceMs={0}
                    descriptionMaxLength={1000}
                    onDescriptionChange={(description) => {
                        if (description !== codeEmail?.description) {
                            updateCodeEmail({ description })
                        }
                    }}
                    nameSuffix={
                        codeEmail ? (
                            <span className="flex flex-wrap items-center gap-1 ml-1">
                                <Tooltip title="The key comes from your code. Send under a new key to start a new email.">
                                    <IconInfo className="text-secondary text-base" />
                                </Tooltip>
                                <CodeBadge sourceUrl={codeEmail.source_url} />
                                {codeEmail.sensitive && (
                                    <Tooltip title="PostHog keeps no copy of what each email contained, and doesn't track link clicks.">
                                        <LemonTag type="highlight" icon={<IconLock />}>
                                            Sensitive
                                        </LemonTag>
                                    </Tooltip>
                                )}
                            </span>
                        ) : undefined
                    }
                    actions={
                        <More
                            size="small"
                            overlay={
                                <LemonButton
                                    fullWidth
                                    status="danger"
                                    disabledReason="Your code creates this email again on its next send. Stop sending with this key first."
                                >
                                    Delete
                                </LemonButton>
                            }
                        />
                    }
                />
                {codeEmail && (
                    <SceneTags
                        tags={codeEmail.tags}
                        onSave={(tags) => updateCodeEmail({ tags })}
                        canEdit={!editDisabledReason}
                        loading={saving}
                        dataAttrKey="code-email"
                    />
                )}
            </div>
            {!codeEmail ? (
                <LemonSkeleton className="h-100" />
            ) : (
                // The reused workflow tabs read workflowLogic without props, so bind it to this email's workflow.
                <BindLogic logic={workflowLogic} props={{ id: codeEmail.hog_flow_id }}>
                    <LemonTabs
                        activeKey={tab}
                        onChange={setTab}
                        tabs={[
                            {
                                key: 'metrics',
                                label: 'Metrics',
                                content: <WorkflowMetrics id={codeEmail.hog_flow_id} onShowInvocations={showSends} />,
                            },
                            {
                                key: 'sends',
                                label: 'Sends',
                                content: <WorkflowInvocations id={codeEmail.hog_flow_id} />,
                            },
                            { key: 'api', label: 'API', content: <CodeEmailApiExample templateKey={codeEmail.key} /> },
                        ]}
                    />
                </BindLogic>
            )}
        </SceneContent>
    )
}
