import type { ExperimentApi } from '@/api/experiments'
import type { HeaderMenuItem } from '@/features/views/screen/HeaderMenu'
import { ArchiveIcon } from '@/ui/icons/ArchiveIcon'
import { CopyIcon } from '@/ui/icons/CopyIcon'
import { ExternalLinkIcon } from '@/ui/icons/ExternalLinkIcon'
import { FlagIcon } from '@/ui/icons/FlagIcon'
import { PauseIcon } from '@/ui/icons/PauseIcon'
import { PencilIcon } from '@/ui/icons/PencilIcon'
import { PlayIcon } from '@/ui/icons/PlayIcon'

import type { ExperimentSheet } from './actionHooks'
import { experimentStatusOf } from './experimentModel'

export type ExperimentMenuSheet = Extract<ExperimentSheet, 'pause' | 'resume' | 'edit_conclusion' | 'archive'>

export interface ExperimentMenuHandlers {
    /** Opens an action sheet through the screen's `useExperimentActions()` controller. */
    onOpenSheet: (sheet: ExperimentMenuSheet) => void
    /** Undefined disables the row, for example when the host has no safe web URL. */
    onOpenWeb?: () => void
    onCopyLink?: () => void
    onOpenFlag?: () => void
}

/**
 * The More menu rows for one experiment, in display order. Pass them to `HeaderMenu`. The rare verbs live here: Pause
 * or Resume while live, Edit conclusion and Archive once complete. Each one confirms in a sheet.
 */
export function experimentMenuItems(experiment: ExperimentApi, handlers: ExperimentMenuHandlers): HeaderMenuItem[] {
    const { onOpenSheet, onOpenWeb, onCopyLink, onOpenFlag } = handlers
    const items: HeaderMenuItem[] = [
        {
            key: 'web',
            label: 'Open on web',
            Icon: ExternalLinkIcon,
            disabled: !onOpenWeb,
            onPress: () => onOpenWeb?.(),
        },
        { key: 'copy', label: 'Copy link', Icon: CopyIcon, disabled: !onCopyLink, onPress: () => onCopyLink?.() },
        {
            key: 'flag',
            label: 'Open feature flag',
            Icon: FlagIcon,
            disabled: !onOpenFlag,
            onPress: () => onOpenFlag?.(),
        },
    ]
    switch (experimentStatusOf(experiment)) {
        case 'running':
        case 'frozen':
            if (experiment.feature_flag_rule_id != null) break
            items.push({
                key: 'pause',
                label: 'Pause experiment',
                Icon: PauseIcon,
                onPress: () => onOpenSheet('pause'),
            })
            break
        case 'paused':
            if (experiment.feature_flag_rule_id != null) break
            items.push({
                key: 'resume',
                label: 'Resume experiment',
                Icon: PlayIcon,
                onPress: () => onOpenSheet('resume'),
            })
            break
        case 'complete':
            items.push({
                key: 'edit-conclusion',
                label: 'Edit conclusion',
                Icon: PencilIcon,
                onPress: () => onOpenSheet('edit_conclusion'),
            })
            if (!experiment.archived) {
                items.push({
                    key: 'archive',
                    label: 'Archive',
                    Icon: ArchiveIcon,
                    onPress: () => onOpenSheet('archive'),
                })
            }
            break
        case 'draft':
            break
    }
    return items
}
