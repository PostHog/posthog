import { useValues } from 'kea'
import { type ReactNode, useCallback, useId, useRef, useState } from 'react'

import { IconLock, IconQuestion, IconX } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'
import { InboxGithubAccessReasons } from './InboxGithubAccessReasons'

export function InboxGithubAccessExplanation({ children }: { children?: ReactNode }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { hasGithubIntegration, isGithubOptionalSetup, isQuickSetup, quickSetupSkipsGithub } =
        useValues(inboxSetupLogic)
    const [visible, setVisible] = useState(false)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const contentId = useId()
    const focusContent = useCallback((element: HTMLDivElement | null) => {
        element?.focus({ preventScroll: true })
    }, [])

    if (
        hasGithubIntegration ||
        (isQuickSetup ? quickSetupSkipsGithub : isGithubOptionalSetup) ||
        featureFlags[FEATURE_FLAGS.SELF_DRIVING_GITHUB_ACCESS_EXPLANATION] !== 'test'
    ) {
        return <>{children}</>
    }

    return (
        <>
            <Popover
                visible={visible}
                placement="bottom-start"
                padded={false}
                onClickOutside={(event) => {
                    setVisible(false)
                    if (event.type === 'keydown') {
                        triggerRef.current?.focus({ preventScroll: true })
                    }
                }}
                overlay={
                    <div
                        id={contentId}
                        ref={focusContent}
                        role="dialog"
                        aria-label="Why do we ask for GitHub access?"
                        tabIndex={-1}
                        className="flex w-128 max-w-full flex-col gap-3 p-4 text-sm text-secondary"
                    >
                        <InboxGithubAccessReasons
                            pullRequests={{
                                title: 'You review every change.',
                                description:
                                    'Fixes arrive as pull requests for you to review and merge. You can turn off PR generation in settings.',
                            }}
                            action={
                                <LemonButton
                                    size="xsmall"
                                    type="tertiary"
                                    icon={<IconX />}
                                    aria-label="Close GitHub access explanation"
                                    data-attr="inbox-github-access-explanation-close"
                                    onClick={() => {
                                        setVisible(false)
                                        triggerRef.current?.focus({ preventScroll: true })
                                    }}
                                />
                            }
                        />
                    </div>
                }
            >
                <LemonButton
                    ref={triggerRef}
                    size="xsmall"
                    type="tertiary"
                    icon={<IconQuestion />}
                    sideIcon={null}
                    aria-haspopup="dialog"
                    aria-expanded={visible}
                    aria-controls={visible ? contentId : undefined}
                    data-attr="inbox-github-access-explanation"
                    onClick={() => setVisible(!visible)}
                >
                    Why GitHub access?
                </LemonButton>
            </Popover>
            {children}
            <LemonButton
                size="xsmall"
                type="tertiary"
                icon={<IconLock />}
                to="https://posthog.com/docs/self-driving/security"
                targetBlank
                data-attr="inbox-github-access-security"
            >
                Security
            </LemonButton>
        </>
    )
}
