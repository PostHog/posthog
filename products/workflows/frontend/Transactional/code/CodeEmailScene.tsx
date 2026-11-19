import { useActions, useValues } from 'kea'

import { IconCopy, IconInfo, IconLock } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonSkeleton, LemonTag, Tooltip } from '@posthog/lemon-ui'

import { NotFound } from 'lib/components/NotFound'
import { SceneTags } from 'lib/components/Scenes/SceneTags'
import { useResizeBreakpoints } from 'lib/hooks/useResizeObserver'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { ProductKey } from '~/queries/schema/schema-general'

import { CodeBadge } from './CodeBadge'
import { CodeEmailLogicProps, codeEmailLogic } from './codeEmailLogic'
import { CodeEmailTabs } from './CodeEmailTabs'
import { SourceRow } from './SourceRow'

export const scene: SceneExport<CodeEmailLogicProps> = {
    component: CodeEmailScene,
    logic: codeEmailLogic,
    paramsToProps: ({ params: { id } }): CodeEmailLogicProps => ({ id }),
    productKey: ProductKey.WORKFLOWS,
}

const ACTION_BREAKPOINTS = { 0: 'narrow', 760: 'wide' } as const

export function CodeEmailScene(): JSX.Element {
    // The scene binds the logic to the email ID in the URL.
    const { codeEmail, loadState, saving, editDisabledReason } = useValues(codeEmailLogic)
    const { loadCodeEmail, updateCodeEmail, setSourceFormOpen, copyAgentPrompt } = useActions(codeEmailLogic)
    const { ref: widthRef, size } = useResizeBreakpoints(ACTION_BREAKPOINTS, { initialSize: 'wide' })

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
            <div ref={widthRef} className="flex flex-col gap-2">
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
                        <>
                            <LemonButton
                                type="secondary"
                                size="small"
                                icon={<IconCopy />}
                                tooltip="Copy a prompt that tells your coding agent which email to change and where"
                                onClick={copyAgentPrompt}
                                disabledReason={!codeEmail ? 'Loading the email' : undefined}
                                data-attr="code-email-copy-agent-prompt"
                            >
                                {size === 'narrow' ? 'Agent prompt' : 'Copy prompt for your agent'}
                            </LemonButton>
                            <More
                                size="small"
                                overlay={
                                    <>
                                        <LemonButton
                                            fullWidth
                                            onClick={() => setSourceFormOpen(true)}
                                            disabledReason={editDisabledReason ?? undefined}
                                            data-attr="code-email-change-source-file"
                                        >
                                            {codeEmail?.source_url ? 'Change source file' : 'Link source file'}
                                        </LemonButton>
                                        <LemonButton
                                            fullWidth
                                            status="danger"
                                            disabledReason="Your code creates this email again on its next send. Stop sending with this key first."
                                        >
                                            Delete
                                        </LemonButton>
                                    </>
                                }
                            />
                        </>
                    }
                />
                <SourceRow />
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
            {!codeEmail ? <LemonSkeleton className="h-100" /> : <CodeEmailTabs codeEmail={codeEmail} />}
        </SceneContent>
    )
}
