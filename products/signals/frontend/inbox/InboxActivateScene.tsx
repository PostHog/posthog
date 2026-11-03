import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, Spinner } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { inboxAgentActivationLogic } from './logics/inboxAgentActivationLogic'

export function InboxActivateScene(): JSX.Element {
    const { error, withoutGithub } = useValues(inboxAgentActivationLogic)
    const { start } = useActions(inboxAgentActivationLogic)

    return (
        <SceneContent>
            <div className="mx-auto flex w-full max-w-xl flex-col gap-4 py-8">
                <h1 className="text-xl font-semibold">Activate Self-driving</h1>
                {error ? (
                    <LemonBanner type="error">
                        <span>{error}</span>
                        <LemonButton size="small" onClick={start} data-attr="inbox-agent-setup-retry">
                            Retry
                        </LemonButton>
                    </LemonBanner>
                ) : (
                    <div className="flex items-center gap-2" role="status">
                        <Spinner />
                        <span>{withoutGithub ? 'Opening setup…' : 'Connecting to GitHub…'}</span>
                    </div>
                )}
                <LemonButton type="tertiary" to={urls.inbox()} className="self-start">
                    Open inbox
                </LemonButton>
            </div>
        </SceneContent>
    )
}

export const scene: SceneExport = { component: InboxActivateScene, logic: inboxAgentActivationLogic }
