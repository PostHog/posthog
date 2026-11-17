import { useActions } from 'kea'

import { IconCalendar } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { releaseLogic } from './releaseLogic'
import { ReleaseScheduleButton } from './ReleaseScheduleButton'
import { ReleaseScheduleFlagSearch } from './ReleaseScheduleFlagSearch'
import { ReleaseRow } from './releaseUtils'

const RESOURCE_TYPE = 'release'
const SCHEDULE_MENU_LIMIT = 10

export function ReleaseSceneMenuBar({ row }: { row: ReleaseRow }): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ReleaseSceneMenuBarInner row={row} /> : null
}

function ReleaseSceneMenuBarInner({ row }: { row: ReleaseRow }): JSX.Element {
    const { openSchedule } = useActions(releaseLogic)
    const scheduleId = `${RESOURCE_TYPE}-menubar-schedule`
    const schedulePin = { order: 1, variant: 'primary' as const, render: () => <ReleaseScheduleButton row={row} /> }

    const scheduleActions: SceneAction[] =
        row.flags.length === 0
            ? []
            : row.flags.length === 1
              ? [
                    {
                        group: 'edit',
                        id: scheduleId,
                        label: 'Schedule a change',
                        icon: <IconCalendar />,
                        opensFloatingUi: true,
                        onSelect: () => openSchedule(row.flags[0].id),
                        pinned: schedulePin,
                    },
                ]
              : row.flags.length > SCHEDULE_MENU_LIMIT
                ? [
                      {
                          group: 'edit',
                          type: 'panel',
                          id: scheduleId,
                          label: 'Schedule a change',
                          icon: <IconCalendar />,
                          render: () => <ReleaseScheduleFlagSearch row={row} />,
                          pinned: schedulePin,
                      },
                  ]
                : [
                      {
                          group: 'edit',
                          type: 'submenu',
                          id: scheduleId,
                          label: 'Schedule a change',
                          icon: <IconCalendar />,
                          items: row.flags.map((flag) => ({
                              id: `${scheduleId}-${flag.id}`,
                              // pinned: data-attr values are wire strings
                              dataAttr: 'release-schedule-flag',
                              label: flag.key,
                              opensFloatingUi: true,
                              onSelect: () => openSchedule(flag.id),
                          })),
                          pinned: schedulePin,
                      },
                  ]

    return <SceneActions actions={scheduleActions} dataAttrKey={RESOURCE_TYPE} />
}
