import { useState } from 'react'

import { Popover } from '@posthog/lemon-ui'

import type { InboxSummaryPersonApi } from '../../../generated/api.schemas'

export function InboxSummaryPeoplePopover({ people }: { people: InboxSummaryPersonApi[] }): JSX.Element {
    const [visible, setVisible] = useState(false)
    const count = people.length

    return (
        <Popover
            visible={visible}
            placement="bottom-start"
            showArrow
            padded={false}
            onClickOutside={() => setVisible(false)}
            onMouseEnterInside={() => setVisible(true)}
            onMouseLeaveInside={() => setVisible(false)}
            overlay={
                <div
                    role="dialog"
                    aria-label="People who approved or merged"
                    className="max-h-80 w-64 overflow-y-auto p-2"
                >
                    <p className="m-0 px-1 pb-1 text-xs font-semibold">People who approved or merged</p>
                    {people.length > 0 ? (
                        <ul className="m-0 flex list-none flex-col gap-0.5 p-0">
                            {people.map((person) => (
                                <li key={person.id} className="truncate rounded px-1 py-0.5 text-xs">
                                    @{person.login}
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="m-0 px-1 text-xs text-secondary">No people approved or merged these PRs.</p>
                    )}
                </div>
            }
        >
            <button
                type="button"
                className="m-0 inline cursor-pointer border-0 bg-transparent p-0 font-semibold text-default underline decoration-dotted underline-offset-2 hover:text-accent"
                aria-label={`Show ${count} ${count === 1 ? 'person' : 'people'}`}
                aria-haspopup="dialog"
                aria-expanded={visible}
                data-attr="inbox-value-summary-people"
                onMouseEnter={() => setVisible(true)}
                onMouseLeave={() => setVisible(false)}
                onClick={() => setVisible(!visible)}
            >
                <span>{`${count.toLocaleString()} ${count === 1 ? 'person' : 'people'}`}</span>
            </button>
        </Popover>
    )
}
