import { useEffect, useState } from 'react'

import { LemonButton, LemonCheckbox, LemonInput, LemonModal } from '@posthog/lemon-ui'

import { DatePicker } from 'lib/components/DatePicker/DatePicker'
import { dayjs } from 'lib/dayjs'

const SUGGESTED_REASONS = [
    'Non-deterministic rendering (animations, timestamps)',
    'Font hinting varies across environments',
    'Async content loading race condition',
    'Known flaky — fix in progress',
]

const DEFAULT_EXPIRY_DAYS = 30

const COPY = {
    create: {
        modalTitle: 'Quarantine snapshot',
        confirmLabel: 'Quarantine',
        dataAttrConfirm: 'visual-review-quarantine-confirm',
        expiresLabel: 'Expires',
        description:
            'Quarantined identifiers appear as quarantined immediately and are excluded from gating when future runs finalize — including pending runs on other branches. Snapshots are still captured and diffed, just not gated on.',
    },
    extend: {
        modalTitle: 'Extend quarantine',
        confirmLabel: 'Extend',
        dataAttrConfirm: 'visual-review-quarantine-extend-confirm',
        expiresLabel: 'New expiry',
        description:
            'Extending creates a new quarantine entry that supersedes the current one — the audit trail keeps both. The reason can be edited; the expiry will be bumped to the date you pick below.',
    },
} as const

// Bump from the current expiry, not "now", when extending. Falls back to a
// fresh +30d window if the prior entry already expired.
function computeDefaultExpiry(initialExpiresAt: string | null | undefined): dayjs.Dayjs {
    if (initialExpiresAt) {
        const prior = dayjs(initialExpiresAt)
        const base = prior.isAfter(dayjs()) ? prior : dayjs()
        return base.add(DEFAULT_EXPIRY_DAYS, 'day')
    }
    return dayjs().add(DEFAULT_EXPIRY_DAYS, 'day')
}

/**
 * Identifiers carry an optional `--light` / `--dark` theme suffix.
 * When the user quarantines one variant, they almost always want
 * the sibling quarantined too — same code path, same flake.
 */
function getThemeSibling(identifier: string): string | null {
    const parts = identifier.split('--')
    const themeIndex = [...parts].reverse().findIndex((part) => part === 'dark' || part === 'light')
    if (themeIndex === -1) {
        return null
    }
    const actualIndex = parts.length - 1 - themeIndex
    const siblingParts = [...parts]
    siblingParts[actualIndex] = siblingParts[actualIndex] === 'dark' ? 'light' : 'dark'
    return siblingParts.join('--')
}

export type QuarantineModalMode = 'create' | 'extend'

export type OnQuarantine = (
    reason: string,
    identifiers: string[],
    expiresAt: string | null,
    sourceRunId: string | null
) => void

interface QuarantineModalProps {
    isOpen: boolean
    onClose: () => void
    identifier: string
    onQuarantine: OnQuarantine
    /**
     * "extend" mode reuses this modal to bump an active quarantine's expiry — the
     * backend create endpoint auto-supersedes the prior active row, so extending
     * is just a re-create with a pre-populated reason and a future date. The
     * sibling-quarantine checkbox is hidden because the sibling has its own
     * quarantine row already.
     */
    mode?: QuarantineModalMode
    /** Pre-fill the reason field. Useful when extending. */
    initialReason?: string
    /** Pre-fill the expiry field. Useful when extending (default: +30d from now). */
    initialExpiresAt?: string | null
    /**
     * The run whose failing snapshot prompted this quarantine. Set when extending
     * (carries forward the original source) or when creating from the run scene.
     * Forwarded to the parent via `onQuarantine` so the backend can store it.
     */
    sourceRunId?: string | null
}

/**
 * Quarantine form in a modal. The parent owns the open state and the API call
 * via `onQuarantine`, so a trigger other than `QuarantineAction` can open it.
 */
export function QuarantineModal({
    isOpen,
    onClose,
    identifier,
    onQuarantine,
    mode = 'create',
    initialReason,
    initialExpiresAt,
    sourceRunId,
}: QuarantineModalProps): JSX.Element {
    const isExtend = mode === 'extend'
    const copy = COPY[mode]

    const [reason, setReason] = useState(initialReason ?? '')
    const [includeSibling, setIncludeSibling] = useState(true)
    const [expiresAt, setExpiresAt] = useState<dayjs.Dayjs | null>(() => computeDefaultExpiry(initialExpiresAt))

    // Re-prefill if the parent swaps which entry we're acting on mid-session.
    // Skip while the modal is open so a background refresh of the underlying
    // entry can't silently trample the user's in-progress edits.
    useEffect(() => {
        if (isOpen) {
            return
        }
        setReason(initialReason ?? '')
        setIncludeSibling(true)
        setExpiresAt(computeDefaultExpiry(initialExpiresAt))
    }, [initialReason, initialExpiresAt, isOpen])

    const sibling = getThemeSibling(identifier)

    const handleSubmit = (): void => {
        const identifiers = [identifier]
        // Extending only affects the entry the user opened — siblings have
        // their own quarantine and their own expiry to manage.
        if (!isExtend && sibling && includeSibling) {
            identifiers.push(sibling)
        }
        onQuarantine(reason, identifiers, expiresAt ? expiresAt.toISOString() : null, sourceRunId ?? null)
        onClose()
    }

    return (
        <LemonModal
            isOpen={isOpen}
            onClose={onClose}
            title={copy.modalTitle}
            footer={
                <>
                    <LemonButton type="secondary" onClick={onClose} data-attr="visual-review-quarantine-cancel">
                        Cancel
                    </LemonButton>
                    <LemonButton
                        type="primary"
                        disabledReason={!reason.trim() ? 'Reason is required' : undefined}
                        onClick={handleSubmit}
                        data-attr={copy.dataAttrConfirm}
                    >
                        {copy.confirmLabel}
                    </LemonButton>
                </>
            }
        >
            <div className="space-y-4">
                <p className="text-sm text-muted">{copy.description}</p>

                <div>
                    <label className="text-sm font-medium mb-1 block">Identifier</label>
                    <div className="font-mono text-xs text-muted bg-bg-3000 rounded px-2 py-1.5">{identifier}</div>
                    {!isExtend && sibling && (
                        <LemonCheckbox
                            className="mt-1.5"
                            label={
                                <span className="text-xs">
                                    Also quarantine <span className="font-mono">{sibling}</span>
                                </span>
                            }
                            checked={includeSibling}
                            onChange={setIncludeSibling}
                        />
                    )}
                </div>

                <div>
                    <label className="text-sm font-medium mb-1 block">Reason</label>
                    <LemonInput
                        placeholder="Why is this snapshot quarantined?"
                        value={reason}
                        onChange={setReason}
                        autoFocus
                    />
                    <div className="flex flex-wrap gap-1 mt-1.5">
                        {SUGGESTED_REASONS.map((suggestion) => (
                            <button
                                key={suggestion}
                                type="button"
                                className="text-[11px] text-muted hover:text-default bg-bg-3000 hover:bg-border rounded px-1.5 py-0.5 transition-colors"
                                onClick={() => setReason(suggestion)}
                            >
                                {suggestion}
                            </button>
                        ))}
                    </div>
                </div>

                <div>
                    <label className="text-sm font-medium mb-1 block">{copy.expiresLabel}</label>
                    <DatePicker
                        value={expiresAt}
                        onChange={setExpiresAt}
                        placeholder="No expiry"
                        clearable
                        maxDate={dayjs().add(1, 'year')}
                    />
                </div>
            </div>
        </LemonModal>
    )
}
