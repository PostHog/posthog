import { useActions, useValues } from 'kea'

import { IconPlay, IconTrash, IconUpload } from '@posthog/icons'
import { LemonButton, LemonFileInput, LemonSelect, LemonSlider, LemonSwitch } from '@posthog/lemon-ui'

import { MAX_CUSTOM_TURN_SOUND_SECONDS, TURN_SOUND_OPTIONS } from '../lib/turnSounds'
import { taskTurnNotificationLogic } from '../logics/taskTurnNotificationLogic'

export function TaskTurnNotificationSettings(): JSX.Element {
    const { browserNotificationsEnabled, sound, volume, customSound, isNotificationSupported, isPermissionDenied } =
        useValues(taskTurnNotificationLogic)
    const { setBrowserNotificationsEnabled, setSound, setVolume, previewSound, uploadCustomSound, removeCustomSound } =
        useActions(taskTurnNotificationLogic)

    const soundOptions = customSound
        ? [...TURN_SOUND_OPTIONS, { value: 'custom' as const, label: `Custom: ${customSound.name}` }]
        : TURN_SOUND_OPTIONS

    return (
        <div className="flex flex-col gap-3 max-w-200">
            <LemonSwitch
                bordered
                fullWidth
                label="Show a browser notification"
                checked={browserNotificationsEnabled}
                onChange={setBrowserNotificationsEnabled}
                disabledReason={
                    !isNotificationSupported
                        ? 'This browser does not support notifications'
                        : isPermissionDenied
                          ? 'Notifications are blocked for this site. Allow them in your browser settings.'
                          : undefined
                }
                data-attr="task-turn-notification-browser"
            />
            <div className="flex flex-wrap items-center gap-2">
                <LemonSelect
                    value={sound}
                    onChange={setSound}
                    options={soundOptions}
                    size="small"
                    data-attr="task-turn-notification-sound"
                />
                <LemonButton
                    type="secondary"
                    size="small"
                    icon={<IconPlay />}
                    onClick={previewSound}
                    disabledReason={sound === 'none' ? 'Pick a sound first' : undefined}
                >
                    Play
                </LemonButton>
                {customSound && (
                    <LemonButton
                        type="secondary"
                        status="danger"
                        size="small"
                        icon={<IconTrash />}
                        onClick={removeCustomSound}
                        tooltip="Remove custom sound"
                    />
                )}
            </div>
            <LemonFileInput
                accept="audio/*"
                multiple={false}
                showUploadedFiles={false}
                onChange={(files) => files[0] && uploadCustomSound(files[0])}
                callToAction={
                    <span className="flex items-center gap-1" data-attr="task-turn-notification-upload">
                        <IconUpload />
                        {`${customSound ? 'Replace the custom sound' : 'Upload a custom sound'} (${MAX_CUSTOM_TURN_SOUND_SECONDS} seconds or less)`}
                    </span>
                }
            />
            {sound !== 'none' && (
                <div className="flex items-center gap-3 max-w-100">
                    <span className="text-secondary shrink-0">Volume</span>
                    <LemonSlider value={volume} onChange={setVolume} min={0} max={100} className="flex-1" />
                </div>
            )}
        </div>
    )
}
