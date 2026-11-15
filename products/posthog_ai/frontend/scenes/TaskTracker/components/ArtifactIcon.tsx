import {
    IconBolt,
    IconCode,
    IconCursor,
    IconDashboard,
    IconDatabase,
    IconDocument,
    IconExternal,
    IconFlask,
    IconGraph,
    IconImage,
    IconListCheck,
    IconMessage,
    IconNotebook,
    IconPeople,
    IconPerson,
    IconRewindPlay,
    IconSparkles,
    IconToggle,
    IconVideoCamera,
    IconWarning,
} from '@posthog/icons'

import type { TaskRunArtifactResponseApi } from 'products/tasks/frontend/generated/api.schemas'

import { ArtifactPreviewKind, LivingVersion, artifactPreviewKind, postHogObjectRef } from '../taskRunArtifacts'

function KindIcon({ kind, className }: { kind: ArtifactPreviewKind; className?: string }): JSX.Element {
    const Icon =
        kind === 'html'
            ? IconCode
            : kind === 'image'
              ? IconImage
              : kind === 'video'
                ? IconVideoCamera
                : kind === 'csv'
                  ? IconDatabase
                  : IconDocument
    return <Icon className={className} />
}

const OBJECT_KIND_ICONS: Record<string, typeof IconGraph> = {
    insight: IconGraph,
    hogql: IconDatabase,
    dashboard: IconDashboard,
    error: IconWarning,
    replay: IconRewindPlay,
    flag: IconToggle,
    experiment: IconFlask,
    survey: IconMessage,
    ticket: IconMessage,
    report: IconNotebook,
    trace: IconSparkles,
    eval: IconListCheck,
    event: IconBolt,
    cohort: IconPeople,
    action: IconCursor,
    person: IconPerson,
}

interface ArtifactIconProps {
    artifact: TaskRunArtifactResponseApi & { living?: LivingVersion }
    className?: string
}

export function ArtifactIcon({ artifact, className }: ArtifactIconProps): JSX.Element {
    const ref = postHogObjectRef(artifact)
    if (ref) {
        const Icon = OBJECT_KIND_ICONS[ref.objectKind] ?? IconExternal
        return <Icon className={className} />
    }
    return <KindIcon kind={artifactPreviewKind(artifact)} className={className} />
}
