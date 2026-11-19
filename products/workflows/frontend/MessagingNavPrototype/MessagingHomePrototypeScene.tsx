// PROTOTYPE, never merged: PostHog/michaelr-context#419. The Email & Messaging home under /messaging, in three variants.
import { useValues } from 'kea'
import { router } from 'kea-router'

import { LemonButton, LemonDivider } from '@posthog/lemon-ui'

import { SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { SceneTitleSection } from '~/layout/scenes/components/SceneTitleSection'
import { messagingNavPrototypeLogic } from '~/layout/today/messagingNavPrototype/messagingNavPrototypeLogic'
import {
    MESSAGING_NAV_GROUPS,
    MESSAGING_PRODUCT_NAME,
    MESSAGING_SECTION_ICONS,
    MESSAGING_SECTION_LABELS,
    MESSAGING_SECTION_META,
    MessagingSection,
    messagingSectionForPath,
    messagingSectionUrl,
} from '~/layout/today/messagingNavPrototype/messagingNavPrototypeNav'
import { MessagingNavPrototypeNewButton } from '~/layout/today/messagingNavPrototype/MessagingNavPrototypeNewButton'

import { MESSAGING_SECTION_CONTENT } from './MessagingHomePrototypeSections'

export const scene: SceneExport = {
    component: MessagingHomePrototypeScene,
}

/** Variant A: the home brings its own sidebar inside the scene, like Settings does. */
function InSceneSidebar({ active }: { active: MessagingSection }): JSX.Element {
    return (
        <nav className="flex w-52 shrink-0 flex-col gap-px" aria-label={MESSAGING_PRODUCT_NAME}>
            {MESSAGING_NAV_GROUPS.map((group, index) => (
                <div key={index} className="flex flex-col gap-px">
                    {group.label ? (
                        <div className="mt-3 mb-1 px-2 text-xxs font-semibold uppercase tracking-wide text-secondary">
                            {group.label}
                        </div>
                    ) : (
                        index > 0 && <LemonDivider className="my-2" />
                    )}
                    {group.sections.map((section) => (
                        <LemonButton
                            key={section}
                            size="small"
                            fullWidth
                            icon={MESSAGING_SECTION_ICONS[section]}
                            active={active === section}
                            to={messagingSectionUrl(section)}
                            sideIcon={
                                MESSAGING_SECTION_META[section] ? (
                                    <span className="text-xs font-normal text-secondary">
                                        {MESSAGING_SECTION_META[section]}
                                    </span>
                                ) : undefined
                            }
                            data-attr={`messaging-prototype-scene-row-${section}`}
                        >
                            {MESSAGING_SECTION_LABELS[section]}
                        </LemonButton>
                    ))}
                </div>
            ))}
        </nav>
    )
}

export function MessagingHomePrototypeScene(): JSX.Element {
    const { location } = useValues(router)
    const { variant } = useValues(messagingNavPrototypeLogic)
    const section = messagingSectionForPath(location.pathname) ?? 'broadcasts'
    const Content = MESSAGING_SECTION_CONTENT[section]
    const inScene = variant === 'A'

    return (
        <SceneContent>
            <SceneTitleSection
                // With the pane in the app sidebar, the pane names the product and the page names the row.
                name={inScene ? MESSAGING_PRODUCT_NAME : MESSAGING_SECTION_LABELS[section]}
                description={
                    inScene ? 'Broadcasts, transactional emails and messaging workflows, with their setup.' : undefined
                }
                resourceType={{ type: 'transactional' }}
                actions={<MessagingNavPrototypeNewButton inline />}
            />
            {inScene ? (
                <div className="flex gap-6">
                    <InSceneSidebar active={section} />
                    <div className="flex min-w-0 flex-1 flex-col gap-3">
                        <h2 className="m-0 text-lg font-semibold">{MESSAGING_SECTION_LABELS[section]}</h2>
                        <Content />
                    </div>
                </div>
            ) : (
                <Content />
            )}
        </SceneContent>
    )
}
