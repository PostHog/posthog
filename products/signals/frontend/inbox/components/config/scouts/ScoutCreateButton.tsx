import React, { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, type LemonButtonProps } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { captureScoutAction } from '../../../inboxAnalytics'
import type { ScoutCreateInitialValues } from '../../../logics/scoutCreateModalLogic'

const LazyScoutCreateModal = React.lazy(async () => {
    const { ScoutCreateModal } = await import('./ScoutCreateModal')
    return { default: ScoutCreateModal }
})

export interface ScoutCreateButtonProps {
    children?: React.ReactNode
    className?: string
    /**
     * When set, the button delegates opening to the parent, which hosts the modal at a stable
     * location (the inbox scene). This keeps the modal and its typed form alive across a fleet
     * re-render or a viewport resize. Without it the button hosts the modal itself.
     */
    onClick?: () => void
    initialValues?: ScoutCreateInitialValues
    onCreated?: (scout: SignalScoutCreateResponseApi) => void
    disabledReason?: string | null
    size?: LemonButtonProps['size']
    type?: LemonButtonProps['type']
    'data-attr'?: string
}

/** Opens the scout form. Paired with `ScoutSuggestButton`, which drafts one with AI instead. */
export function ScoutCreateButton({
    onClick,
    initialValues,
    onCreated,
    disabledReason,
    children = 'Create scout',
    className,
    size = 'small',
    type = 'primary',
    'data-attr': dataAttr,
}: ScoutCreateButtonProps): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const creationDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.LlmSkill,
        AccessControlLevel.Editor
    )

    return (
        <>
            <LemonButton
                type={type}
                size={size}
                icon={<IconPlus />}
                disabledReason={creationDisabledReason ?? disabledReason ?? undefined}
                onClick={onClick ?? (() => setIsModalOpen(true))}
                className={className}
                data-attr={dataAttr}
            >
                {children}
            </LemonButton>
            {!onClick && isModalOpen ? (
                <React.Suspense fallback={null}>
                    <LazyScoutCreateModal
                        isOpen
                        initialValues={initialValues}
                        onCreated={(scout) => {
                            captureScoutAction({
                                actionType: 'create_scout',
                                surface: 'fleet_list',
                                skillName: scout.config.skill_name,
                            })
                            onCreated?.(scout)
                        }}
                        onClose={() => setIsModalOpen(false)}
                    />
                </React.Suspense>
            ) : null}
        </>
    )
}
