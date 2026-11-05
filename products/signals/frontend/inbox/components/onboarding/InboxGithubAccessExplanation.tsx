import { useValues } from 'kea'
import { type ReactNode, useCallback, useId, useRef, useState } from 'react'

import { IconLock, IconQuestion, IconX } from '@posthog/icons'
import { LemonButton, Popover } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { inboxSetupLogic } from '../../logics/inboxSetupLogic'

export function InboxGithubAccessExplanation({ children }: { children?: ReactNode }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const { hasGithubIntegration, isGithubOptionalSetup } = useValues(inboxSetupLogic)
    const [visible, setVisible] = useState(false)
    const triggerRef = useRef<HTMLButtonElement>(null)
    const contentId = useId()
    const focusContent = useCallback((element: HTMLDivElement | null) => {
        element?.focus({ preventScroll: true })
    }, [])

    if (
        hasGithubIntegration ||
        isGithubOptionalSetup ||
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
                        <div className="flex items-start justify-between gap-3">
                            <p className="m-0 font-semibold text-default">
                                We use GitHub access to research issues and may automatically open pull requests with
                                proposed fixes.
                            </p>
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
                        </div>
                        <ul className="m-0 list-none space-y-3 p-0">
                            <li>
                                <h4 className="m-0 text-sm font-semibold text-default">Find root causes</h4>
                                <p className="m-0">
                                    Code access allows us to accurately identify root causes by comparing the behavior
                                    we see in your product with its implementation.
                                </p>
                            </li>
                            <li>
                                <h4 className="m-0 text-sm font-semibold text-default">Find the change behind a bug</h4>
                                <p className="m-0">
                                    Code history allows us to correlate changes in behavior with changes in the code.
                                    Our reports are more useful if we can point to a specific PR that may have
                                    introduced a user-affecting bug.
                                </p>
                            </li>
                            <li>
                                <h4 className="m-0 text-sm font-semibold text-default">Reach the right people</h4>
                                <p className="m-0">
                                    GitHub commit history lets us assign reports more accurately because we can tell
                                    which team members care about an issue.
                                </p>
                            </li>
                            <li>
                                <h4 className="m-0 text-sm font-semibold text-default">Automatic fixes</h4>
                                <p className="m-0">We can open PRs to fix issues we've researched automatically.</p>
                            </li>
                        </ul>
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
