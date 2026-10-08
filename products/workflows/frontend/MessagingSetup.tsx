import { useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    MESSAGING_SETUP_TAB_KEYS,
    MESSAGING_TAB_CONTENT,
    MESSAGING_TAB_LABELS,
    MessagingNavTabKey,
    MessagingSetupTabKey,
} from './messagingTabs'
import { MessagingSetupGuide } from './setupGuide/MessagingSetupGuide'
import { MessagingSetupMenuStatus } from './setupGuide/MessagingSetupMenuStatus'

export interface MessagingSetupProps {
    tab: MessagingSetupTabKey
    linkFor: (tab: MessagingNavTabKey) => string
}

/** The sending setup tabs behind one "Messaging" tab, with a side menu that keeps each tab's own URL. */
export function MessagingSetup({ tab, linkFor }: MessagingSetupProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const guidedOnboardingEnabled = !!featureFlags[FEATURE_FLAGS.WORKFLOWS_GUIDED_ONBOARDING]

    return (
        <>
            {guidedOnboardingEnabled && <MessagingSetupGuide linkFor={linkFor} />}
            <div className="flex flex-col gap-4 @min-[48rem]/main-content:flex-row">
                <nav
                    className="flex flex-row flex-wrap gap-1 shrink-0 @min-[48rem]/main-content:flex-col @min-[48rem]/main-content:w-52"
                    aria-label="Messaging"
                >
                    {MESSAGING_SETUP_TAB_KEYS.map((key) => (
                        <LemonButton
                            key={key}
                            size="small"
                            to={linkFor(key)}
                            active={key === tab}
                            sideIcon={guidedOnboardingEnabled ? <MessagingSetupMenuStatus tab={key} /> : undefined}
                            data-attr={`messaging-setup-menu-${key}`}
                        >
                            {MESSAGING_TAB_LABELS[key]}
                        </LemonButton>
                    ))}
                </nav>
                <div className="flex-1 min-w-0">{MESSAGING_TAB_CONTENT[tab]}</div>
            </div>
        </>
    )
}
