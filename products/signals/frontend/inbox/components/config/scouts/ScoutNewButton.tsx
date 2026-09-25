import { useValues } from 'kea'
import { useState } from 'react'

import { IconChat, IconDocument, IconPlus } from '@posthog/icons'
import { LemonButton, type LemonButtonProps, LemonMenu, LemonTag } from '@posthog/lemon-ui'

import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'
import { SKILL_DESCRIPTION_MAX_LENGTH } from 'products/skills/frontend/skillConstants'

import {
    captureScoutCreatePathChosen,
    captureScoutCreatePathSwitched,
    type ScoutSurface,
} from '../../../inboxAnalytics'
import type { ScoutCreateInitialValues } from '../../../logics/scoutCreateModalLogic'
import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { SCOUT_CHAT_PROMPT_MAX_LENGTH, ScoutChatModal } from './ScoutChatModal'
import { ScoutCreateModalHost, useScoutCreateDisabledReason } from './ScoutCreateModalHost'

type OpenScoutModal = { kind: 'chat'; prompt: string } | { kind: 'form'; initialValues: ScoutCreateInitialValues }

export interface ScoutNewButtonProps {
    /** `menu` puts both ways in behind one button. `buttons` shows them side by side. */
    layout?: 'menu' | 'buttons'
    surface: ScoutSurface
    onCreated?: (scout: SignalScoutCreateResponseApi) => void
    size?: LemonButtonProps['size']
}

/**
 * The two ways to create a scout: a chat with an agent (recommended), or the form. Each modal links
 * to the other and carries the typed text across. Callers that prefill the form use `ScoutCreateButton`.
 */
export function ScoutNewButton({
    layout = 'menu',
    surface,
    onCreated,
    size = 'small',
}: ScoutNewButtonProps): JSX.Element {
    const [openModal, setOpenModal] = useState<OpenScoutModal | null>(null)
    const { runningChatType, aiConsentDisabledReason } = useValues(scoutFleetLogic)
    const creationDisabledReason = useScoutCreateDisabledReason()
    const chatDisabledReason =
        aiConsentDisabledReason ?? (runningChatType !== null ? 'Starting another task…' : null) ?? undefined

    const openChat = (): void => {
        captureScoutCreatePathChosen({ path: 'chat', surface })
        setOpenModal({ kind: 'chat', prompt: '' })
    }
    const openForm = (): void => {
        captureScoutCreatePathChosen({ path: 'form', surface })
        setOpenModal({ kind: 'form', initialValues: {} })
    }

    return (
        <>
            {layout === 'menu' ? (
                <LemonMenu
                    items={[
                        {
                            label: (
                                <ScoutNewMenuItemLabel
                                    title="Chat with an agent"
                                    description="Say what you want watched. The agent checks your data and builds the scout with you."
                                    recommended
                                />
                            ),
                            icon: <IconChat />,
                            onClick: openChat,
                            disabledReason: chatDisabledReason,
                            'data-attr': 'scout-new-chat',
                        },
                        {
                            label: (
                                <ScoutNewMenuItemLabel
                                    title="Fill in the form"
                                    description="You already know the instructions, schedule and where reports go."
                                />
                            ),
                            icon: <IconDocument />,
                            onClick: openForm,
                            'data-attr': 'scout-new-form',
                        },
                    ]}
                    placement="bottom-end"
                >
                    <LemonButton
                        type="primary"
                        size={size}
                        icon={<IconPlus />}
                        disabledReason={creationDisabledReason ?? undefined}
                        data-attr="scout-new"
                    >
                        New scout
                    </LemonButton>
                </LemonMenu>
            ) : (
                <>
                    <LemonButton
                        type="primary"
                        size={size}
                        icon={<IconChat />}
                        disabledReason={creationDisabledReason ?? chatDisabledReason}
                        onClick={openChat}
                        data-attr="scout-new-chat"
                    >
                        Chat with an agent
                    </LemonButton>
                    <LemonButton
                        type="secondary"
                        size={size}
                        icon={<IconDocument />}
                        disabledReason={creationDisabledReason ?? undefined}
                        onClick={openForm}
                        data-attr="scout-new-form"
                    >
                        Fill in the form
                    </LemonButton>
                </>
            )}
            {openModal?.kind === 'chat' ? (
                <ScoutChatModal
                    initialPrompt={openModal.prompt}
                    onClose={() => setOpenModal(null)}
                    onSwitchToForm={(prompt) => {
                        captureScoutCreatePathSwitched({ direction: 'chat_to_form', surface })
                        setOpenModal({
                            kind: 'form',
                            initialValues: prompt ? { description: prompt.slice(0, SKILL_DESCRIPTION_MAX_LENGTH) } : {},
                        })
                    }}
                />
            ) : null}
            <ScoutCreateModalHost
                initialValues={openModal?.kind === 'form' ? openModal.initialValues : null}
                onClose={() => setOpenModal(null)}
                onCreated={onCreated}
                onSwitchToChat={(description) => {
                    captureScoutCreatePathSwitched({ direction: 'form_to_chat', surface })
                    setOpenModal({ kind: 'chat', prompt: description.slice(0, SCOUT_CHAT_PROMPT_MAX_LENGTH) })
                }}
            />
        </>
    )
}

function ScoutNewMenuItemLabel({
    title,
    description,
    recommended = false,
}: {
    title: string
    description: string
    recommended?: boolean
}): JSX.Element {
    return (
        <div className="flex max-w-80 flex-col gap-0.5 py-1">
            <span className="flex items-center gap-2 font-semibold">
                {title}
                {recommended ? (
                    <LemonTag type="success" size="small">
                        Recommended
                    </LemonTag>
                ) : null}
            </span>
            <span className="whitespace-normal text-xs font-normal text-secondary">{description}</span>
        </div>
    )
}
