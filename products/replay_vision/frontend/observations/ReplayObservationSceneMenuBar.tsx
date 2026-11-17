import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconArrowLeft, IconArrowRight, IconChat, IconShare } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { KeyboardShortcut } from 'lib/lemon-ui/KeyboardShortcut/KeyboardShortcut'
import { LinkPrimitive } from 'lib/lemon-ui/Link'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { replayVisionFeedbackAction } from '../components/replayVisionFeedbackAction'
import { NOTES_BUTTON_TOOLTIP } from './ObservationNotesButton'
import { openObservationShareDialog } from './ObservationShareButton'
import { QuillObservationNotesButton } from './QuillObservationNotesButton'
import { replayObservationSceneLogic } from './replayObservationSceneLogic'

const RESOURCE_TYPE = 'replay-observation'

interface ReplayObservationSceneMenuBarProps {
    previousUrl: string | undefined
    nextUrl: string | undefined
    neighborsPending: boolean
    neighborsFiltered: boolean
    observationId: string
    sessionRecordingId: string
    playerKey: string
}

export function ReplayObservationSceneMenuBar(props: ReplayObservationSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <ReplayObservationSceneMenuBarInner {...props} /> : null
}

function ReplayObservationSceneMenuBarInner({
    previousUrl,
    nextUrl,
    neighborsPending,
    neighborsFiltered,
    observationId,
    sessionRecordingId,
    playerKey,
}: ReplayObservationSceneMenuBarProps): JSX.Element {
    const { notesPanelOpen, notesDisabledReason } = useValues(replayObservationSceneLogic)
    const { toggleNotesPanel } = useActions(replayObservationSceneLogic)

    const previousDisabledReason =
        previousUrl || neighborsPending
            ? undefined
            : neighborsFiltered
              ? 'No previous observation matching your filters'
              : 'No newer observation'
    const nextDisabledReason =
        nextUrl || neighborsPending
            ? undefined
            : neighborsFiltered
              ? 'No next observation matching your filters'
              : 'No older observation'
    const previousTooltip = neighborsFiltered
        ? 'Previous observation matching your filters'
        : 'Previous (newer) observation for this scanner'
    const nextTooltip = neighborsFiltered
        ? 'Next observation matching your filters'
        : 'Next (older) observation for this scanner'

    const actions: SceneAction[] = [
        {
            group: 'file',
            id: `${RESOURCE_TYPE}-menubar-share`,
            label: 'Share',
            icon: <IconShare />,
            opensFloatingUi: true,
            tooltip: 'Copy a link to this observation, starting the recording where you are',
            onSelect: () => openObservationShareDialog({ observationId, sessionRecordingId, playerKey }),
            // pinned: data-attr values are wire strings
            pinned: { order: 2, variant: 'secondary', dataAttr: 'vision-observation-share' },
        },
        {
            group: 'view',
            section: 'navigate',
            id: `${RESOURCE_TYPE}-menubar-previous`,
            label: 'Previous observation',
            icon: <IconArrowLeft />,
            tooltip: previousTooltip,
            shortcut: 'K',
            disabledReason: neighborsPending ? 'Loading observations' : previousDisabledReason,
            onSelect: () => previousUrl && router.actions.push(previousUrl),
            pinned: {
                order: 1,
                variant: 'icon',
                render: () => (
                    <Button
                        variant="outline"
                        loading={neighborsPending}
                        render={previousUrl ? <LinkPrimitive to={previousUrl} /> : undefined}
                        disabledReason={previousDisabledReason}
                        tooltip={
                            <>
                                {previousTooltip} <KeyboardShortcut k />
                            </>
                        }
                        data-attr="vision-observation-prev"
                    >
                        <IconArrowLeft />
                        Previous
                    </Button>
                ),
            },
        },
        {
            group: 'view',
            section: 'navigate',
            id: `${RESOURCE_TYPE}-menubar-next`,
            label: 'Next observation',
            icon: <IconArrowRight />,
            tooltip: nextTooltip,
            shortcut: 'J',
            disabledReason: neighborsPending ? 'Loading observations' : nextDisabledReason,
            onSelect: () => nextUrl && router.actions.push(nextUrl),
            pinned: {
                order: 2,
                variant: 'icon',
                render: () => (
                    <Button
                        variant="outline"
                        loading={neighborsPending}
                        render={nextUrl ? <LinkPrimitive to={nextUrl} /> : undefined}
                        disabledReason={nextDisabledReason}
                        tooltip={
                            <>
                                {nextTooltip} <KeyboardShortcut j />
                            </>
                        }
                        data-attr="vision-observation-next"
                    >
                        Next
                        <IconArrowRight />
                    </Button>
                ),
            },
        },
        {
            group: 'view',
            section: 'panels',
            type: 'checkbox',
            id: `${RESOURCE_TYPE}-menubar-notes`,
            label: 'Notes',
            icon: <IconChat />,
            tooltip: NOTES_BUTTON_TOOLTIP,
            disabledReason: notesDisabledReason ?? undefined,
            checked: notesPanelOpen,
            onCheckedChange: () => toggleNotesPanel(),
            pinned: { order: 1, variant: 'secondary', render: () => <QuillObservationNotesButton /> },
        },
        replayVisionFeedbackAction(RESOURCE_TYPE),
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
