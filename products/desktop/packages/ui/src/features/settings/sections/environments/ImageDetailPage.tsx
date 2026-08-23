import { ArrowLeft } from "@phosphor-icons/react";
import { Badge, Button, Input, Label, Text } from "@posthog/quill";
import {
  isImageBuildFailed,
  isImageBuildInProgress,
  type SandboxCustomImage,
} from "@posthog/shared/domain-types";
import { CodeMirrorEditor } from "@posthog/ui/features/code-editor/components/CodeMirrorEditor";
import { useHandleOpenTask } from "@posthog/ui/features/deep-links/useHandleOpenTask";
import { BuildLogPane } from "@posthog/ui/features/settings/sections/environments/BuildLogPane";
import { imageFailureDetail } from "@posthog/ui/features/settings/sections/environments/imageBuildWatcher";
import {
  useSandboxCustomImageDetail,
  useSandboxCustomImages,
} from "@posthog/ui/features/settings/sections/environments/useSandboxCustomImages";
import { toast } from "@posthog/ui/primitives/toast";
import { useId, useState } from "react";

interface ImageDetailPageProps {
  image: SandboxCustomImage;
  /** Names of the environments starting from this image. */
  usedBy: readonly string[];
  onDone: () => void;
}

/**
 * One image, with everything it needs on one page: what it is called, what it
 * builds from, and how the last build went. The list only links here, so an
 * expanding row never buries the rest of the settings page.
 */
export function ImageDetailPage({
  image,
  usedBy,
  onDone,
}: ImageDetailPageProps) {
  const { data } = useSandboxCustomImageDetail(image.id);
  const { buildMutation, builderTaskMutation, updateMutation, deleteMutation } =
    useSandboxCustomImages();
  const handleOpenTask = useHandleOpenTask();
  const nameId = useId();
  const current = data ?? image;
  const [name, setName] = useState(current.name);
  const [spec, setSpec] = useState<string | null>(null);
  const specYaml = spec ?? current.spec_yaml ?? "";
  const nameChanged = name.trim() !== "" && name.trim() !== current.name;
  const specChanged = spec !== null && spec !== (current.spec_yaml ?? "");
  const building = isImageBuildInProgress(current.status);

  const save = async () => {
    if (nameChanged) {
      await updateMutation.mutateAsync({ id: current.id, name: name.trim() });
    }
    if (specChanged) {
      await buildMutation.mutateAsync({ id: current.id, specYaml });
      setSpec(null);
    }
  };

  const openBuilder = async () => {
    const updated = await builderTaskMutation.mutateAsync(current.id);
    if (updated.builder_task_id) void handleOpenTask(updated.builder_task_id);
  };

  const archive = async () => {
    if (usedBy.length > 0) {
      toast.error(
        `${usedBy.length} environment${usedBy.length === 1 ? "" : "s"} still start from this image`,
        { description: usedBy.join(", ") },
      );
      return;
    }
    await deleteMutation.mutateAsync(current.id);
    onDone();
  };

  return (
    <div className="flex flex-col gap-5">
      <button
        type="button"
        onClick={onDone}
        className="flex w-fit cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-(--gray-11) text-[12px] hover:text-(--gray-12)"
      >
        <ArrowLeft size={10} />
        <span>Back to environments</span>
      </button>

      <div className="flex flex-wrap items-center gap-2">
        <Badge
          variant={
            current.status === "ready"
              ? "success"
              : isImageBuildFailed(current.status)
                ? "destructive"
                : "default"
          }
          className="text-[10.5px]"
        >
          {building && (
            <span className="mr-1 inline-block size-1.5 animate-pulse rounded-full bg-current" />
          )}
          {current.status}
        </Badge>
        {current.version > 0 && (
          <Text className="text-(--gray-10) text-[11.5px] tabular-nums">
            v{current.version}
          </Text>
        )}
        {current.repository && (
          <Text className="text-(--gray-10) text-[11.5px]">
            {current.repository}
          </Text>
        )}
        <Text className="text-(--gray-10) text-[11.5px]">
          {usedBy.length === 0
            ? "No environment starts from it yet"
            : `Used by ${usedBy.join(", ")}`}
        </Text>
      </div>

      {isImageBuildFailed(current.status) && (
        <Text className="text-(--red-11) text-[12px]">
          {imageFailureDetail(current)}
        </Text>
      )}

      <div className="flex max-w-[420px] flex-col gap-2">
        <Label htmlFor={nameId} className="font-medium text-[12.5px]">
          Name
        </Label>
        <Input
          id={nameId}
          className="h-8 text-[12.5px]"
          value={name}
          data-attr="image-detail-name"
          onChange={(event) => setName(event.target.value)}
        />
      </div>

      <div className="flex flex-col gap-2 border-(--gray-4) border-t border-dashed pt-5">
        <Label className="font-medium text-[12.5px]">Build spec</Label>
        <Text className="max-w-[60ch] text-(--gray-10) text-[11.5px] leading-snug">
          What the image installs, as YAML. Saving a change starts a new build,
          and the version goes up.
        </Text>
        {/* filePath drives the language mode, so this is a real YAML editor. */}
        {/* A definite height: the editor fills its parent and scrolls inside,
            so min/max alone would clip instead of scroll. */}
        <div className="h-[380px] overflow-hidden rounded-(--radius-3) border border-(--gray-5)">
          <CodeMirrorEditor
            content={specYaml}
            filePath="image-spec.yaml"
            onContentChange={setSpec}
          />
        </div>
      </div>

      <div className="flex flex-col gap-2 border-(--gray-4) border-t border-dashed pt-5">
        <Label className="font-medium text-[12.5px]">Last build</Label>
        <BuildLogPane image={current} />
      </div>

      <div className="flex items-center gap-3 border-(--gray-4) border-t pt-4">
        <Button
          variant="link-muted"
          size="sm"
          loading={deleteMutation.isPending}
          disabled={deleteMutation.isPending}
          data-attr="image-detail-archive"
          onClick={() => void archive()}
        >
          Archive
        </Button>
        <div className="ml-auto flex shrink-0 items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            loading={builderTaskMutation.isPending}
            disabled={builderTaskMutation.isPending}
            data-attr="image-detail-builder"
            onClick={() => void openBuilder()}
          >
            Work it out in a session
          </Button>
          <Button
            variant="primary"
            size="sm"
            loading={buildMutation.isPending || updateMutation.isPending}
            disabled={
              (!nameChanged && !specChanged) ||
              buildMutation.isPending ||
              updateMutation.isPending
            }
            data-attr="image-detail-save"
            onClick={() => void save()}
          >
            {specChanged ? "Save and rebuild" : "Save"}
          </Button>
        </div>
      </div>
    </div>
  );
}
