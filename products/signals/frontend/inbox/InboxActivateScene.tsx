import { useActions, useValues } from 'kea'

import { IconCheckCircle, IconWarning } from '@posthog/icons'
import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { Logo } from 'lib/brand'
import { AuthSceneBackdrop } from 'scenes/authentication/shared/authScene/AuthSceneBackdrop'
import { SceneExport } from 'scenes/sceneTypes'

import { inboxAgentActivationLogic } from './logics/inboxAgentActivationLogic'
import { inboxSetupLogic } from './logics/inboxSetupLogic'

export function InboxActivateScene(): JSX.Element {
    const { view, error, withoutGithub, hasGithubIntegration } = useValues(inboxAgentActivationLogic)
    const { retry, connectGithub } = useActions(inboxAgentActivationLogic)
    const { activateQuickSetup } = useActions(inboxSetupLogic)

    return (
        <AuthSceneBackdrop className="flex min-h-screen flex-col items-center justify-center px-4 py-8">
            <div className="flex w-full max-w-md flex-col">
                <span className="AuthScene__logo mx-auto mb-6 block shrink-0">
                    <Logo size="lg" />
                </span>
                <div
                    className="AuthScene__card flex flex-col items-center gap-3 p-8 text-center"
                    role={view === 'error' ? 'alert' : 'status'}
                >
                    {view === 'done' ? (
                        <>
                            <IconCheckCircle className="text-success text-4xl" />
                            <h1 className="m-0 text-xl font-semibold">Self-driving is on</h1>
                            <p className="m-0 text-sm text-secondary">
                                Go back to your agent to continue. You can close this tab.
                            </p>
                        </>
                    ) : view === 'error' ? (
                        <>
                            <IconWarning className="text-warning text-4xl" />
                            <h1 className="m-0 text-xl font-semibold">Self-driving isn't active yet</h1>
                            <p className="m-0 text-sm text-secondary">{error}</p>
                            <LemonButton type="primary" onClick={retry} data-attr="inbox-agent-setup-retry">
                                Try again
                            </LemonButton>
                        </>
                    ) : view === 'confirm' ? (
                        <>
                            <h1 className="m-0 text-xl font-semibold">Activate Self-driving</h1>
                            {hasGithubIntegration ? (
                                <>
                                    <p className="m-0 text-sm text-secondary">
                                        GitHub is connected. Activate Self-driving to finish setup.
                                    </p>
                                    <LemonButton
                                        type="primary"
                                        onClick={() => activateQuickSetup()}
                                        data-attr="inbox-agent-setup-activate"
                                    >
                                        Activate Self-driving
                                    </LemonButton>
                                </>
                            ) : (
                                <>
                                    <p className="m-0 text-sm text-secondary">GitHub isn't connected yet.</p>
                                    <LemonButton
                                        type="primary"
                                        onClick={connectGithub}
                                        data-attr="inbox-agent-setup-connect-github"
                                    >
                                        Connect GitHub
                                    </LemonButton>
                                </>
                            )}
                        </>
                    ) : (
                        <>
                            <Spinner className="text-3xl" />
                            <h1 className="m-0 text-xl font-semibold">
                                {view === 'activating'
                                    ? 'Activating Self-driving…'
                                    : withoutGithub
                                      ? 'Opening setup…'
                                      : 'Connecting to GitHub…'}
                            </h1>
                            {view === 'activating' || !withoutGithub ? (
                                <p className="m-0 text-sm text-secondary">
                                    {view === 'activating'
                                        ? 'This usually takes a few seconds.'
                                        : 'Self-driving uses GitHub to connect errors to your code.'}
                                </p>
                            ) : null}
                        </>
                    )}
                </div>
            </div>
        </AuthSceneBackdrop>
    )
}

export const scene: SceneExport = { component: InboxActivateScene, logic: inboxAgentActivationLogic }
