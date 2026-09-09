import React, { useState } from 'react'

import { IconPlus } from '@posthog/icons'
import { LemonButton, type LemonButtonProps } from '@posthog/lemon-ui'

import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'

import type { ScoutCreateInitialValues } from '../../../logics/scoutCreateModalLogic'
import { ScoutCreateModalHost, useScoutCreateDisabledReason } from './ScoutCreateModalHost'

export interface ScoutCreateButtonProps {
    children?: React.ReactNode
    className?: string
    initialValues?: ScoutCreateInitialValues
    onCreated?: (scout: SignalScoutCreateResponseApi) => void
    size?: LemonButtonProps['size']
    type?: LemonButtonProps['type']
    'data-attr'?: string
}

/** Opens the scout form. Paired with `ScoutSuggestButton`, which drafts one with AI instead. */
export function ScoutCreateButton({
    initialValues,
    onCreated,
    children = 'Create scout',
    className,
    size = 'small',
    type = 'primary',
    'data-attr': dataAttr,
}: ScoutCreateButtonProps): JSX.Element {
    const [isModalOpen, setIsModalOpen] = useState(false)
    const creationDisabledReason = useScoutCreateDisabledReason()

    return (
        <>
            <LemonButton
                type={type}
                size={size}
                icon={<IconPlus />}
                disabledReason={creationDisabledReason ?? undefined}
                onClick={() => setIsModalOpen(true)}
                className={className}
                data-attr={dataAttr}
            >
                {children}
            </LemonButton>
            <ScoutCreateModalHost
                initialValues={isModalOpen ? (initialValues ?? {}) : null}
                onClose={() => setIsModalOpen(false)}
                onCreated={onCreated}
            />
        </>
    )
}
