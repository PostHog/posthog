// The files a task run hands back, for hosts that show them outside the task page, such as space feed cards.
//
// Kept apart from `./primitives` on purpose: a feed card only needs the icon, the rules and the link, and
// `./primitives` statically pulls the thread presenters and the product data-tool widgets into its chunk.
//
// Part of the `products/posthog_ai/frontend/api/<module>` public surface. Import from here, not from deep
// `../scenes/*` paths. See ../README.md for the tier model and ../AGENTS.md for the coupling rule.

export { captureArtifactChipClicked } from '../scenes/TaskTracker/artifactChipTelemetry'
export { ArtifactIcon } from '../scenes/TaskTracker/components/ArtifactIcon'
export {
    artifactPreviewKind,
    collectRunArtifacts,
    groupArtifactVersions,
    taskArtifactPath,
} from '../scenes/TaskTracker/taskRunArtifacts'
export type { ArtifactFile, ArtifactPreviewKind } from '../scenes/TaskTracker/taskRunArtifacts'
