import { useMemo } from 'react'

import { IconFlag } from '@posthog/icons'

import { iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { TodayExplainerPreview } from '~/layout/today/todayPreviewCards'
import { TodayPreviewTrigger } from '~/layout/today/TodayPreviewTrigger'
import { FileSystemIconType } from '~/queries/schema/schema-general'

import type { ReleaseAllType } from './releaseAllLogic'

const DESCRIPTIONS: Record<ReleaseAllType, string> = {
    release: 'A release. Open it to see its flags, experiments, and early access features.',
    feature_flag: 'A feature flag. Open it to see its rollout, release conditions, and usage.',
    experiment: 'An experiment. Open it to see its variants, metrics, and results.',
    early_access_feature: 'An early access feature. Open it to see its stage and who opted in.',
}

export function releaseSidebarIcon(type: ReleaseAllType): JSX.Element {
    return type === 'release' ? <IconFlag /> : iconForType(type as FileSystemIconType)
}

export function ReleaseSidebarRecordPreview({
    name,
    type,
    children,
}: {
    name: string
    type: ReleaseAllType
    children: JSX.Element
}): JSX.Element {
    // The shared card stores the payload, so it must keep its identity between renders.
    const preview = useMemo<TodayExplainerPreview>(
        () => ({ kind: 'explainer', label: name, icon: releaseSidebarIcon(type), description: DESCRIPTIONS[type] }),
        [name, type]
    )
    return <TodayPreviewTrigger payload={preview}>{children}</TodayPreviewTrigger>
}
