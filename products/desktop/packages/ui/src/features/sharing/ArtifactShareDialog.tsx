import type { TaskArtifactSharing } from "@posthog/api-client/posthog-client";
import { Button, Separator, Text } from "@posthog/quill";
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
import { fileLinkHasUnpublishedChanges } from "./publicLink";
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
  /** The file was uploaded again after the public link was pinned. */
  newerUploadExists: boolean;
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
  newerUploadExists,
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
        description="Anyone with the link can view the file as it was when you shared it. Changes made after that stay private until you publish them."
        dataAttrPrefix="share-artifact"
        onToggle={onToggle}
      >
        {newerUploadExists && (
          <Text
            size="xs"
            variant="muted"
            data-attr="share-artifact-newer-upload"
          >
            The file changed after you shared it. Publish the changes to update
            the public link.
          </Text>
        )}
      </PublicShareSection>
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
  const { setEnabled, updateLink, isPending } = useSetArtifactSharing(
    taskId,
    artifactId,
  );
  const newerUploadExists = fileLinkHasUnpublishedChanges(sharing.data);

  return (
    <ShareDialog
      title="Share file"
      description={name}
      onClose={onClose}
      action={
        newerUploadExists ? (
          <Button
            variant="primary"
            size="sm"
            loading={isPending}
            onClick={() => void updateLink()}
            data-attr="share-artifact-publish-changes"
          >
            Publish changes
          </Button>
        ) : null
      }
    >
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
        newerUploadExists={newerUploadExists}
        onToggle={(enabled) => void setEnabled(enabled)}
      />
    </ShareDialog>
  );
}
