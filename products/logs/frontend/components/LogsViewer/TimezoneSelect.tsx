import { useValues } from 'kea'

import { IconGlobe, IconHome, IconLaptop } from '@posthog/icons'
import { LemonSelect, LemonSelectOptionLeaf, LemonSelectSection } from '@posthog/lemon-ui'

import { shortTimeZone } from 'lib/utils'
import { teamLogic } from 'scenes/teamLogic'

export interface TimezoneSelectProps {
    /** IANA timezone string (e.g. "America/New_York", "Europe/London", "UTC") */
    value: string
    onChange: (timezone: string) => void
    /** Additional IANA timezones to include in the select */
    additionalTimezones?: string[]
    size?: 'xsmall' | 'small' | 'medium'
}

function getLocalTimezone(): string {
    return Intl.DateTimeFormat().resolvedOptions().timeZone
}

export function TimezoneSelect({
    value,
    onChange,
    additionalTimezones = [],
    size = 'small',
}: TimezoneSelectProps): JSX.Element {
    const { currentTeam } = useValues(teamLogic)
    const projectTimezone = currentTeam?.timezone ?? 'UTC'
    const localTimezone = getLocalTimezone()

    const baseOptions: LemonSelectOptionLeaf<string>[] = [
        {
            value: 'UTC',
            label: 'UTC',
            icon: <IconGlobe className="text-muted" />,
        },
        {
            value: localTimezone,
            label: `Local (${shortTimeZone(localTimezone) ?? localTimezone})`,
            icon: <IconLaptop className="text-muted" />,
        },
    ]

    // Only add project option if it's different from UTC and local
    if (projectTimezone !== 'UTC' && projectTimezone !== localTimezone) {
        baseOptions.push({
            value: projectTimezone,
            label: `Project (${shortTimeZone(projectTimezone) ?? projectTimezone})`,
            icon: <IconHome className="text-muted" />,
        })
    }

    // Filter out duplicates from additional timezones
    const seenTimezones = new Set(baseOptions.map((o) => o.value))
    const additionalOptions: LemonSelectOptionLeaf<string>[] = additionalTimezones
        .filter((tz) => !seenTimezones.has(tz))
        .map((tz) => ({
            value: tz,
            label: `${shortTimeZone(tz) ?? tz} (${tz})`,
            icon: <IconGlobe className="text-muted" />,
        }))

    const options: LemonSelectSection<string>[] | LemonSelectOptionLeaf<string>[] =
        additionalOptions.length > 0
            ? [
                  {
                      title: 'Common',
                      options: baseOptions,
                  },
                  {
                      title: 'Other',
                      options: additionalOptions,
                  },
              ]
            : baseOptions

    return (
        <LemonSelect<string>
            value={value}
            onChange={onChange}
            options={options}
            size={size}
            data-attr="timezone-select"
        />
    )
}
