import { useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { QuarantineModal, type OnQuarantine, type QuarantineModalMode } from './QuarantineModal'

const TRIGGER = {
    create: { label: 'Quarantine this identifier', dataAttr: 'visual-review-quarantine-open' },
    extend: { label: 'Extend', dataAttr: 'visual-review-quarantine-extend-open' },
} as const

interface QuarantineActionProps {
    identifier: string
    onQuarantine: OnQuarantine
    /** Override the trigger button label. Defaults to "Quarantine this identifier". */
    triggerLabel?: string
    mode?: QuarantineModalMode
    initialReason?: string
    initialExpiresAt?: string | null
    sourceRunId?: string | null
    /**
     * Set while a quarantine write for this identifier is in flight. The create
     * endpoint supersedes the prior active row, so a second submit writes a
     * second record. Blocks the trigger rather than the modal's submit, because
     * the modal closes as soon as the parent takes over.
     */
    pendingReason?: string | null
}

/**
 * Quarantine trigger button plus its modal. Used from the run scene (per snapshot
 * sidebar) and the snapshot history scene (per identifier banner).
 */
export function QuarantineAction({
    identifier,
    onQuarantine,
    triggerLabel,
    mode = 'create',
    initialReason,
    initialExpiresAt,
    sourceRunId,
    pendingReason,
}: QuarantineActionProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const trigger = TRIGGER[mode]

    return (
        <div>
            <LemonButton
                type="secondary"
                size="small"
                onClick={() => setIsOpen(true)}
                data-attr={trigger.dataAttr}
                loading={!!pendingReason}
                disabledReason={pendingReason ?? undefined}
            >
                {triggerLabel ?? trigger.label}
            </LemonButton>
            <QuarantineModal
                isOpen={isOpen}
                onClose={() => setIsOpen(false)}
                identifier={identifier}
                onQuarantine={onQuarantine}
                mode={mode}
                initialReason={initialReason}
                initialExpiresAt={initialExpiresAt}
                sourceRunId={sourceRunId}
            />
        </div>
    )
}
