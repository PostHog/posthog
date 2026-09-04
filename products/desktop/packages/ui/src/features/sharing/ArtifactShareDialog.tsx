import type { TaskArtifactSharing } from "@posthog/api-client/posthog-client";
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
import { ShareDialog } from "./ShareDialog";
import type { ShareVisibility } from "./shareTarget";
import {
  useArtifactSharingQuery,
  useSetArtifactSharing,
} from "./useArtifactSharing";

export interface ArtifactShareBodyViewProps {
  appUrl: string | null;
  publicUrl: string | null;
  visibility: ShareVisibility;
  sharing: TaskArtifactSharing | null | undefined;
  isLoading: boolean;
  isError: boolean;
  isPending: boolean;
  onToggle: (enabled: boolean) => void;
}

/** The share dialog's file body, given everything it shows. */
export function ArtifactShareBodyView({
  appUrl,
  publicUrl,
  visibility,
  sharing,
  isLoading,
  isError,
  isPending,
  onToggle,
}: ArtifactShareBodyViewProps) {
  return (
    <div className="flex flex-col gap-5">
      <LinkCopyRow
        label="Team link"
        description="For people on your team. Opens the file straight in PostHog Desktop, inside its task."
        url={appUrl}
        copiedDescription="Anyone on your team with access to the task can open the file."
        dataAttr="share-artifact-copy-link"
      />
      <AccessSection visibility={visibility} noun="file" />
      <Separator />
      <PublicShareSection
        sharing={sharing}
        isLoading={isLoading}
        isError={isError}
        isPending={isPending}
        publicUrl={publicUrl}
        description="Anyone with the link can view this version of the file. Versions uploaded later stay private unless you share them."
        dataAttrPrefix="share-artifact"
        onToggle={onToggle}
      />
    </div>
  );
}

export function ArtifactShareDialog({
  taskId,
  artifactId,
  name,
  onClose,
}: {
  taskId: string;
  artifactId: string;
  name: string;
  onClose: () => void;
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
  const sharing = useArtifactSharingQuery(taskId, artifactId);
  const { setEnabled, isPending } = useSetArtifactSharing(taskId, artifactId);

  return (
    <ShareDialog title="Share file" description={name} onClose={onClose}>
      <ArtifactShareBodyView
        appUrl={artifactShareUrl(taskId, artifactId)}
        publicUrl={
          sharing.data?.accessToken
            ? sharedResourceUrl(sharing.data.accessToken)
            : null
        }
        visibility={visibility}
        sharing={sharing.data}
        isLoading={sharing.isLoading}
        isError={sharing.isError}
        isPending={isPending}
        onToggle={(enabled) => void setEnabled(enabled)}
      />
    </ShareDialog>
  );
}
