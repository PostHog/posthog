import { useMemo, useRef } from 'react'

import { IconChevronDown } from '@posthog/icons'
import {
    Combobox,
    ComboboxCollection,
    ComboboxContent,
    ComboboxEmpty,
    ComboboxGroup,
    ComboboxInput,
    ComboboxItem,
    ComboboxLabel,
    ComboboxList,
    ComboboxSeparator,
    ComboboxTrigger,
} from '@posthog/quill'

import { TodaySpaceGlyph } from '~/layout/today/TodaySpaceGlyph'
import { isLockedSpace, spaceLabel } from '~/layout/today/todaySpacesLogic'

import { ChannelDTOApi } from '../generated/api.schemas'
import { NewSessionSpaceGroup } from './newSessionSceneLogic'

export interface NewSessionSpaceSelectProps {
    spaces: ChannelDTOApi[]
    groups: NewSessionSpaceGroup[]
    value: ChannelDTOApi | null
    onChange: (spaceId: string) => void
}

/** The space a new session files into, drawn inside the page heading like PostHog Desktop. */
export function NewSessionSpaceSelect({ spaces, groups, value, onChange }: NewSessionSpaceSelectProps): JSX.Element {
    const anchorRef = useRef<HTMLButtonElement>(null)
    const byId = useMemo(() => new Map(spaces.map((space) => [space.id, space])), [spaces])

    return (
        <Combobox<string>
            items={groups}
            value={value?.id ?? null}
            onValueChange={(spaceId: string | null) => {
                if (spaceId && spaceId !== value?.id) {
                    onChange(spaceId)
                }
            }}
            itemToStringLabel={(spaceId: string) => {
                const space = byId.get(spaceId)
                return space ? spaceLabel(space) : ''
            }}
        >
            <ComboboxTrigger
                render={
                    <button
                        ref={anchorRef}
                        type="button"
                        aria-label="Space"
                        title={value ? spaceLabel(value) : undefined}
                        className="inline-flex max-w-full items-center gap-1.5 border-b-2 border-dashed border-border text-foreground transition-colors hover:border-foreground"
                        data-attr="today-new-session-space"
                    >
                        <span className="min-w-0 truncate">{value ? spaceLabel(value) : 'choose a space'}</span>
                        <IconChevronDown className="size-5 shrink-0" />
                    </button>
                }
            />
            <ComboboxContent anchor={anchorRef} side="bottom" sideOffset={6} className="min-w-56">
                <ComboboxInput placeholder="Search spaces" showTrigger={false} />
                <ComboboxEmpty>No spaces match that name.</ComboboxEmpty>
                <ComboboxList>
                    {(group: NewSessionSpaceGroup, index: number) => (
                        <ComboboxGroup key={group.value} items={group.items}>
                            {index > 0 && <ComboboxSeparator />}
                            <ComboboxLabel>{group.value}</ComboboxLabel>
                            <ComboboxCollection>
                                {(spaceId: string) => {
                                    const space = byId.get(spaceId)
                                    return space ? (
                                        <ComboboxItem key={spaceId} value={spaceId} title={spaceLabel(space)}>
                                            <TodaySpaceGlyph
                                                locked={isLockedSpace(space)}
                                                className="text-muted-foreground"
                                            />
                                            <span className="min-w-0 truncate">{spaceLabel(space)}</span>
                                        </ComboboxItem>
                                    ) : null
                                }}
                            </ComboboxCollection>
                        </ComboboxGroup>
                    )}
                </ComboboxList>
            </ComboboxContent>
        </Combobox>
    )
}
