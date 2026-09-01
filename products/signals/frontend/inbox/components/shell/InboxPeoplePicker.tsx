import clsx from 'clsx'

import { IconAsterisk, IconCheck, IconPerson } from '@posthog/icons'
import { LemonInput, Spinner } from '@posthog/lemon-ui'

import { Popover } from 'lib/lemon-ui/Popover'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'

export interface InboxPerson {
    uuid: string
    name: string
    email: string
    /** Shown after the name in muted text. */
    trailing?: string | number
}

/**
 * The searchable people popover the inbox uses wherever a filter names one person: a search box,
 * an "everyone" row, then a row per person with an avatar. The caller owns the trigger, the open
 * state, and the search query, so the same picker sits behind a segmented control on the reports
 * page and a plain button on the scouts roster, and searches a server or a local list.
 */
export function InboxPeoplePicker({
    visible,
    referenceElement,
    onClose,
    search,
    onSearch,
    people,
    loading = false,
    selectedUuid,
    forYou,
    everyoneLabel,
    onPick,
}: {
    visible: boolean
    referenceElement: HTMLElement | null
    onClose: () => void
    search: string
    onSearch: (query: string) => void
    people: InboxPerson[]
    loading?: boolean
    /** `null` marks the everyone row; `undefined` marks no row at all. */
    selectedUuid: string | null | undefined
    /** Adds a pinned "For you" row above the everyone row (the reports scope filter uses it). */
    forYou?: { active: boolean; onPick: () => void }
    everyoneLabel: string
    onPick: (person: InboxPerson | null) => void
}): JSX.Element {
    return (
        <Popover
            visible={visible}
            onClickOutside={onClose}
            referenceElement={referenceElement}
            placement="bottom-end"
            overlay={
                <div className="w-[240px] p-1">
                    <LemonInput
                        type="search"
                        size="small"
                        placeholder="Search people…"
                        value={search}
                        onChange={onSearch}
                        autoFocus
                        className="mb-1"
                    />
                    <div className="max-h-[16rem] overflow-y-auto space-y-px">
                        {forYou && (
                            <PersonRow
                                active={forYou.active}
                                onClick={forYou.onPick}
                                avatar={
                                    <span
                                        className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-secondary text-tertiary"
                                        aria-hidden
                                    >
                                        <IconPerson className="text-xs" />
                                    </span>
                                }
                                label="For you"
                            />
                        )}
                        <PersonRow
                            active={selectedUuid === null}
                            onClick={() => onPick(null)}
                            avatar={
                                <span
                                    className="inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-dashed border-secondary text-tertiary"
                                    aria-hidden
                                >
                                    <IconAsterisk className="text-xs" />
                                </span>
                            }
                            label={everyoneLabel}
                        />
                        {people.map((person) => (
                            <PersonRow
                                key={person.uuid}
                                active={selectedUuid === person.uuid}
                                onClick={() => onPick(person)}
                                avatar={
                                    <ProfilePicture user={{ first_name: person.name, email: person.email }} size="sm" />
                                }
                                label={person.name || person.email}
                                trailing={person.trailing}
                            />
                        ))}
                        {loading ? (
                            <div className="flex items-center gap-2 px-2 py-1.5 text-xs text-tertiary">
                                <Spinner className="size-3" />
                                Searching…
                            </div>
                        ) : people.length === 0 ? (
                            <div className="px-2 py-1.5 text-xs text-tertiary">No matching people.</div>
                        ) : null}
                    </div>
                </div>
            }
        />
    )
}

function PersonRow({
    active,
    onClick,
    avatar,
    label,
    trailing,
}: {
    active: boolean
    onClick: () => void
    avatar: JSX.Element
    label: string
    trailing?: string | number
}): JSX.Element {
    return (
        <button
            type="button"
            onClick={onClick}
            className={clsx(
                'flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-sm transition-colors',
                active ? 'bg-surface-secondary font-medium' : 'hover:bg-surface-secondary'
            )}
        >
            {avatar}
            <span className="min-w-0 flex-1 truncate">{label}</span>
            {trailing !== undefined && <span className="shrink-0 text-xs text-muted tabular-nums">{trailing}</span>}
            {active && <IconCheck className="shrink-0 text-sm text-default" />}
        </button>
    )
}
