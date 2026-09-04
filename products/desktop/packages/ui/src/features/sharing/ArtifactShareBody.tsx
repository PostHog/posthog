import { Separator } from "@posthog/quill";
import { useChannels } from "@posthog/ui/features/canvas/hooks/useChannels";
import { taskDetailQuery } from "@posthog/ui/features/tasks/queries";
import {
  artifactShareUrl,
  sharedResourceUrl,
} from "@posthog/ui/utils/posthogLinks";
import { useQuery } from "@tanstack/react-query";
import { AccessSection } from "./AccessSection";
import { LinkCopyRow } from "./LinkCopyRow";
import { PublicShareSection } from "./PublicShareSection";
import type { ShareVisibility } from "./shareTarget";
import {
  useArtifactSharingQuery,
  useSetArtifactSharing,
} from "./useArtifactSharing";

export function ArtifactShareBody({
  taskId,
  artifactId,
  name,
}: {
  taskId: string;
  artifactId: string;
  name: string;
}) {
  const task = useQuery(taskDetailQuery(taskId));
  const { channels, isLoading: channelsLoading } = useChannels();
  const channel = channels.find(
    (candidate) => candidate.id === task.data?.channel,
  );
  const visibility: ShareVisibility = channel
    ? channel.channelType === "personal"
      ? "personal"
      : "project"
    : task.isLoading || channelsLoading
      ? "unknown"
      : "project";
  const sharing = useArtifactSharingQuery(taskId, artifactId, name);
  const { setEnabled, isPending } = useSetArtifactSharing(
    taskId,
    artifactId,
    name,
  );
  const publicUrl = sharing.data?.accessToken
    ? sharedResourceUrl(sharing.data.accessToken)
    : null;

  return (
    <div className="flex flex-col gap-5">
      <LinkCopyRow
        label="Link"
        description="Opens the file in PostHog Desktop, inside its task."
        url={artifactShareUrl(taskId, artifactId)}
        copiedDescription="Anyone in this project with access to the task can open the file."
        dataAttr="share-artifact-copy-link"
      />
      <AccessSection visibility={visibility} noun="file" />
      <Separator />
      <PublicShareSection
        sharing={sharing.data}
        isLoading={sharing.isLoading}
        isError={sharing.isError}
        isPending={isPending}
        publicUrl={publicUrl}
        description="Anyone with the link can view the newest version of this file, including versions uploaded later."
        dataAttrPrefix="share-artifact"
        onToggle={(enabled) => void setEnabled(enabled)}
      />
    </div>
  );
}
