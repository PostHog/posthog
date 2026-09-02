import React from 'react'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { SignalScoutCreateResponseApi } from 'products/signals/frontend/generated/api.schemas'

import { captureScoutAction } from '../../../inboxAnalytics'
import type { ScoutCreateInitialValues } from '../../../logics/scoutCreateModalLogic'

const LazyScoutCreateModal = React.lazy(async () => {
    const { ScoutCreateModal } = await import('./ScoutCreateModal')
    return { default: ScoutCreateModal }
})

/** Why the current user can't create a scout, or null when they can. */
export function useScoutCreateDisabledReason(): string | null {
    return getAccessControlDisabledReason(AccessControlResourceType.LlmSkill, AccessControlLevel.Editor)
}

export interface ScoutCreateModalHostProps {
    /** The scout to prefill, or null to render nothing. Doubles as the open state. */
    initialValues: ScoutCreateInitialValues | null
    onClose: () => void
    onCreated?: (scout: SignalScoutCreateResponseApi) => void
}

/**
 * The create-scout modal, lazily loaded and instrumented, with its open state owned by the caller.
 *
 * Split out of `ScoutCreateButton` because a caller that opens the modal from a URL can't host it
 * inside the button: on the AI observability tab the buttons sit in a `LemonCollapse` panel, whose
 * content unmounts while collapsed, so a link would open nothing.
 */
export function ScoutCreateModalHost({
    initialValues,
    onClose,
    onCreated,
}: ScoutCreateModalHostProps): JSX.Element | null {
    if (!initialValues) {
        return null
    }

    return (
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
                onClose={onClose}
            />
        </React.Suspense>
    )
}
