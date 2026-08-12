import {
  ArrowLeft,
  Lock,
  PencilSimple,
  Plus,
  Trash,
  X,
} from "@phosphor-icons/react";
import {
  buildSandboxEnvironmentInput,
  emptyForm,
  type SandboxEnvironmentFormState as FormState,
  formFromEnv,
  validateDomains,
  validateEnvVars,
} from "@posthog/core/settings/sandboxEnvironmentForm";
import {
  isImageBuildFailed,
  isImageBuildInProgress,
  type NetworkAccessLevel,
  type SandboxCustomImage,
  type SandboxCustomImageStatus,
  type SandboxEnvironment,
} from "@posthog/shared/domain-types";
import { useHandleOpenTask } from "@posthog/ui/features/deep-links/useHandleOpenTask";
import { GitHubRepoPicker } from "@posthog/ui/features/folder-picker/GitHubRepoPicker";
import { useCloudRepoPicker } from "@posthog/ui/features/integrations/useCloudRepoPicker";
import { useSettingsPageStore } from "@posthog/ui/features/settings/stores/settingsPageStore";
import { ChevronDownIcon } from "@radix-ui/react-icons";
import {
  AlertDialog,
  Badge,
  Button,
  Checkbox,
  Flex,
  IconButton,
  Text,
  TextArea,
  TextField,
} from "@radix-ui/themes";
import {
  type ComponentProps,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { toast } from "../../../../primitives/toast";
import { imageFailureDetail } from "./imageBuildWatcher";
import { SettingsSelect, type SettingsSelectOption } from "./SettingsSelect";
import {
  useSandboxCustomImageDetail,
  useSandboxCustomImages,
} from "./useSandboxCustomImages";
import { useSandboxEnvironments } from "./useSandboxEnvironments";

const NETWORK_ACCESS_OPTIONS: {
  value: NetworkAccessLevel;
  label: string;
  description: string;
}[] = [
  {
    value: "trusted",
    label: "Trusted",
    description: "Downloads packages from verified sources",
  },
  {
    value: "full",
    label: "Full",
    description: "Unrestricted internet access",
  },
  {
    value: "custom",
    label: "Custom",
    description: "Create a list of allowed domains",
  },
];

function NetworkAccessSelect({
  value,
  onChange,
}: {
  value: NetworkAccessLevel;
  onChange: (v: NetworkAccessLevel) => void;
}) {
  const [open, setOpen] = useState(false);
  const current =
    NETWORK_ACCESS_OPTIONS.find((o) => o.value === value) ??
    NETWORK_ACCESS_OPTIONS[0];

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full cursor-pointer items-center justify-between gap-2 rounded-2 border border-gray-6 bg-transparent px-3 py-2 text-left font-mono text-[13px] text-gray-12 transition-colors hover:border-gray-8"
      >
        <Flex direction="column" gap="0">
          <Text className="text-sm">{current.label}</Text>
          <Text color="gray" className="text-[13px]">
            {current.description}
          </Text>
        </Flex>
        <ChevronDownIcon
          style={{
            transform: open ? "rotate(180deg)" : undefined,
            transition: "transform 150ms",
          }}
          className="shrink-0"
        />
      </button>
      {open && (
        <div className="absolute z-50 mt-1 w-full overflow-hidden rounded-2 border border-gray-6 bg-(--color-panel-solid) shadow-lg">
          {NETWORK_ACCESS_OPTIONS.map((opt) => (
            <button
              type="button"
              key={opt.value}
              onClick={() => {
                onChange(opt.value);
                setOpen(false);
              }}
              className="flex w-full cursor-pointer flex-col gap-0 border-0 bg-transparent px-3 py-2 text-left transition-colors hover:bg-gray-3 data-[active]:bg-accent-4"
              data-active={opt.value === value || undefined}
            >
              <Text
                className={`text-sm ${opt.value === value ? "font-medium" : ""}`}
              >
                {opt.label}
              </Text>
              <Text color="gray" className="text-[13px]">
                {opt.description}
              </Text>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

interface ImageFormState {
  name: string;
  description: string;
  repository: string | null;
  private: boolean;
}

const IMAGE_STATUS_COLORS: Record<
  SandboxCustomImageStatus,
  ComponentProps<typeof Badge>["color"]
> = {
  draft: "gray",
  scanning: "blue",
  building: "blue",
  scan_failed: "red",
  build_failed: "red",
  ready: "green",
  archived: "gray",
};

function imageLabel(image: SandboxCustomImage): string {
  return `${image.name}${image.status !== "ready" ? ` (${image.status})` : ""}`;
}

function BuildLogPane({
  image,
  onClose,
}: {
  image: SandboxCustomImage;
  onClose: () => void;
}) {
  const { data, isLoading } = useSandboxCustomImageDetail(image.id);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickToBottomRef = useRef(true);
  const buildLog = data?.build_log ?? "";
  const status = data?.status ?? image.status;
  const isScanning = status === "scanning";
  const isBuilding = status === "building";

  // biome-ignore lint/correctness/useExhaustiveDependencies: re-run as the log grows to keep the scroll pinned
  useEffect(() => {
    const el = scrollRef.current;
    if (el && stickToBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [buildLog]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    stickToBottomRef.current =
      el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }, []);

  if (isLoading) {
    return (
      <Text color="gray" className="text-[13px]">
        Loading build log...
      </Text>
    );
  }

  if (!buildLog) {
    return (
      <Text color="gray" className="text-[13px]">
        {isScanning
          ? "Security scan in progress — build output will stream once the build starts."
          : isBuilding
            ? "Waiting for build output…"
            : "No build log yet."}
      </Text>
    );
  }

  return (
    <Flex direction="column" gap="1">
      <Flex align="center" justify="between">
        <Flex align="center" gap="2">
          <Text color="gray" className="text-[12px]">
            Build log
          </Text>
          {isBuilding && (
            <Flex align="center" gap="1">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-(--blue-9)" />
              <Text color="blue" className="text-[12px]">
                building — streaming
              </Text>
            </Flex>
          )}
        </Flex>
        <IconButton
          variant="ghost"
          size="1"
          color="gray"
          onClick={onClose}
          aria-label="Close build log"
        >
          <X size={12} />
        </IconButton>
      </Flex>
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="max-h-[320px] overflow-auto rounded-2 border border-gray-6 bg-gray-2 p-2"
      >
        <pre className="m-0 whitespace-pre-wrap break-words font-[var(--code-font-family)] text-gray-12 text-xs">
          {buildLog}
        </pre>
      </div>
    </Flex>
  );
}

function BaseImageSelect({
  value,
  images,
  onChange,
}: {
  value: string | null;
  images: SandboxCustomImage[];
  onChange: (v: string | null) => void;
}) {
  const options: SettingsSelectOption[] = [
    { value: null, label: "Default" },
    ...images.map((img) => ({
      value: img.id,
      label: imageLabel(img),
      disabled: img.status !== "ready",
    })),
  ];

  return (
    <SettingsSelect
      value={value}
      options={options}
      onChange={onChange}
      ariaLabel="Base image"
    />
  );
}

export function CloudEnvironmentsSettings() {
  const {
    environments,
    isLoading,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useSandboxEnvironments();
  const {
    images,
    customImagesEnabled,
    customImagesDisabled,
    createMutation: createImageMutation,
    buildMutation,
    builderTaskMutation,
    deleteMutation: deleteImageMutation,
    updateMutation: updateImageMutation,
  } = useSandboxCustomImages();
  const handleOpenTask = useHandleOpenTask();
  const repoPickerProps = useCloudRepoPicker();
  const consumeInitialAction = useSettingsPageStore(
    (s) => s.consumeInitialAction,
  );
  const setFormMode = useSettingsPageStore((s) => s.setFormMode);
  const [editingEnv, setEditingEnv] = useState<SandboxEnvironment | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [form, setForm] = useState<FormState>(emptyForm());
  const [imageForm, setImageForm] = useState<ImageFormState | null>(null);
  const [editingSpecImageId, setEditingSpecImageId] = useState<string | null>(
    null,
  );
  const [specDraft, setSpecDraft] = useState("");
  const [deleteConfirmImage, setDeleteConfirmImage] =
    useState<SandboxCustomImage | null>(null);
  const [renameImage, setRenameImage] = useState<SandboxCustomImage | null>(
    null,
  );
  const [renameName, setRenameName] = useState("");
  const [viewingLogImageId, setViewingLogImageId] = useState<string | null>(
    null,
  );

  useEffect(() => {
    const action = consumeInitialAction();
    if (action === "create") {
      setForm(emptyForm());
      setEditingEnv(null);
      setIsCreating(true);
    }
  }, [consumeInitialAction]);

  const isFormOpen = isCreating || editingEnv !== null;

  useEffect(() => {
    setFormMode(isFormOpen);
    return () => setFormMode(false);
  }, [isFormOpen, setFormMode]);

  const domainValidation = useMemo(() => {
    if (form.network_access_level !== "custom")
      return { domains: [], errors: [] };
    return validateDomains(form.allowed_domains_text);
  }, [form.network_access_level, form.allowed_domains_text]);

  const envVarValidation = useMemo(
    () => validateEnvVars(form.environment_variables_text),
    [form.environment_variables_text],
  );

  const hasValidationErrors =
    domainValidation.errors.length > 0 || envVarValidation.errors.length > 0;

  const openCreate = useCallback(() => {
    setForm(emptyForm());
    setEditingEnv(null);
    setIsCreating(true);
  }, []);

  const openEdit = useCallback((env: SandboxEnvironment) => {
    setForm(formFromEnv(env));
    setEditingEnv(env);
    setIsCreating(false);
  }, []);

  const closeForm = useCallback(() => {
    setEditingEnv(null);
    setIsCreating(false);
  }, []);

  const handleSave = useCallback(async () => {
    if (hasValidationErrors) {
      toast.error("Fix validation errors before saving");
      return;
    }

    const payload = buildSandboxEnvironmentInput(
      form,
      domainValidation.domains,
      envVarValidation.vars,
    );
    if (customImagesDisabled) {
      delete payload.custom_image_id;
    }

    if (editingEnv) {
      await updateMutation.mutateAsync({ id: editingEnv.id, ...payload });
    } else {
      await createMutation.mutateAsync(payload);
    }
    closeForm();
  }, [
    form,
    editingEnv,
    hasValidationErrors,
    domainValidation,
    envVarValidation,
    customImagesDisabled,
    createMutation,
    updateMutation,
    closeForm,
  ]);

  const handleDelete = useCallback(async () => {
    if (!editingEnv) return;
    await deleteMutation.mutateAsync(editingEnv.id);
    closeForm();
  }, [editingEnv, deleteMutation, closeForm]);

  const openCreateImage = useCallback(() => {
    setImageForm({
      name: "",
      description: "",
      repository: null,
      private: false,
    });
  }, []);

  const patchImageForm = useCallback((patch: Partial<ImageFormState>) => {
    setImageForm((current) => (current ? { ...current, ...patch } : current));
  }, []);

  const handleCreateImage = useCallback(async () => {
    if (!imageForm) return;
    const image = await createImageMutation.mutateAsync({
      name: imageForm.name.trim(),
      ...(imageForm.description.trim()
        ? { description: imageForm.description.trim() }
        : {}),
      ...(imageForm.repository ? { repository: imageForm.repository } : {}),
      ...(imageForm.private ? { private: true } : {}),
    });
    setImageForm(null);
    if (image.builder_task_id) {
      void handleOpenTask(image.builder_task_id);
    }
  }, [imageForm, createImageMutation, handleOpenTask]);

  const handleOpenBuilder = useCallback(
    async (image: SandboxCustomImage) => {
      const updated = await builderTaskMutation.mutateAsync(image.id);
      if (updated.builder_task_id) {
        void handleOpenTask(updated.builder_task_id);
      }
    },
    [builderTaskMutation, handleOpenTask],
  );

  const handleSaveSpec = useCallback(
    async (image: SandboxCustomImage) => {
      await buildMutation.mutateAsync({ id: image.id, specYaml: specDraft });
      setEditingSpecImageId(null);
    },
    [buildMutation, specDraft],
  );

  const confirmDeleteImage = useCallback(() => {
    if (!deleteConfirmImage) return;
    deleteImageMutation.mutate(deleteConfirmImage.id);
    setDeleteConfirmImage(null);
  }, [deleteConfirmImage, deleteImageMutation]);

  const openRenameImage = useCallback((image: SandboxCustomImage) => {
    setRenameImage(image);
    setRenameName(image.name);
  }, []);

  const handleRenameImage = useCallback(async () => {
    if (!renameImage) return;
    const name = renameName.trim();
    if (!name) {
      toast.error("Name cannot be blank");
      return;
    }
    if (name === renameImage.name) {
      setRenameImage(null);
      return;
    }
    try {
      await updateImageMutation.mutateAsync({ id: renameImage.id, name });
      setRenameImage(null);
    } catch {
      // The mutation's onError callback displays the failure toast.
    }
  }, [renameImage, renameName, updateImageMutation]);

  if (isFormOpen) {
    return (
      <Flex direction="column" gap="4">
        <button
          type="button"
          onClick={closeForm}
          className="flex w-fit cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-[12px] text-gray-11 hover:text-gray-12"
        >
          <ArrowLeft size={10} />
          <span>Back to environments</span>
        </button>

        <Text className="font-medium text-[13px]">
          {editingEnv
            ? `Editing cloud environment ${editingEnv.name}`
            : "Creating cloud environment"}
        </Text>
        {editingEnv && (
          <Text color="gray" className="text-[12px]">
            Changes take effect on the next session that uses this environment;
            running sessions are not affected.
          </Text>
        )}

        <Flex direction="column" gap="1">
          <Text className="font-medium text-sm">Name</Text>
          <Text color="gray" className="text-[13px]">
            Shown in the workspace picker. Pick a name that describes the access
            profile, e.g. "Internal APIs" or "Read-only".
          </Text>
          <TextField.Root
            size="2"
            value={form.name}
            onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            placeholder="e.g. Dev 1"
          />
        </Flex>

        {customImagesEnabled && (
          <Flex direction="column" gap="1">
            <Text className="font-medium text-sm">Base image</Text>
            <Text color="gray" className="text-[13px]">
              The sandbox image sessions in this environment start from.{" "}
              <Text color="gray" className="font-medium text-[13px]">
                Default
              </Text>{" "}
              is the standard image; custom images must finish building before
              they can be selected.
            </Text>
            <BaseImageSelect
              value={form.custom_image_id}
              images={images}
              onChange={(v) => setForm((f) => ({ ...f, custom_image_id: v }))}
            />
          </Flex>
        )}

        <Flex direction="column" gap="1">
          <Text className="font-medium text-sm">Network access</Text>
          <Text color="gray" className="text-[13px]">
            Controls which hosts the sandbox may reach.{" "}
            <Text color="gray" className="font-medium text-[13px]">
              Full
            </Text>{" "}
            allows any outbound traffic.{" "}
            <Text color="gray" className="font-medium text-[13px]">
              Trusted sources only
            </Text>{" "}
            restricts traffic to a curated list of common package registries and
            source hosts.{" "}
            <Text color="gray" className="font-medium text-[13px]">
              Custom
            </Text>{" "}
            lets you define an explicit allowlist below.
          </Text>
          <NetworkAccessSelect
            value={form.network_access_level}
            onChange={(v) =>
              setForm((f) => ({ ...f, network_access_level: v }))
            }
          />
        </Flex>

        {form.network_access_level === "custom" && (
          <>
            <Flex direction="column" gap="1">
              <Text className="font-medium text-sm">Allowed domains</Text>
              <Text color="gray" className="text-[13px]">
                One domain per line (not URLs — no scheme or path). Use{" "}
                <Text color="gray" className="font-medium text-[13px]">
                  *
                </Text>{" "}
                as a wildcard, e.g.{" "}
                <Text color="gray" className="font-medium text-[13px]">
                  *.example.com
                </Text>{" "}
                to cover all subdomains. Requests to any other host are blocked.
              </Text>
              <TextArea
                size="2"
                rows={4}
                value={form.allowed_domains_text}
                onChange={(e) =>
                  setForm((f) => ({
                    ...f,
                    allowed_domains_text: e.target.value,
                  }))
                }
                placeholder={"github.com\n*.example.com"}
                color={domainValidation.errors.length > 0 ? "red" : undefined}
                className="font-[var(--code-font-family)] [&_textarea]:text-xs"
              />
              {domainValidation.errors.length > 0 && (
                <Flex direction="column" gap="0">
                  {domainValidation.errors.map((err) => (
                    <Text key={err} color="red" className="text-[13px]">
                      {err}
                    </Text>
                  ))}
                </Flex>
              )}
            </Flex>

            <Flex align="center" gap="2">
              <Checkbox
                size="1"
                checked={form.include_default_domains}
                onCheckedChange={(checked) =>
                  setForm((f) => ({
                    ...f,
                    include_default_domains: checked === true,
                  }))
                }
              />
              <Text color="gray" className="text-[13px]">
                Also include the built-in list of common package managers and
                source hosts — recommended unless you deliberately want to block
                them.
              </Text>
            </Flex>
          </>
        )}

        <Flex direction="column" gap="1">
          <Text className="font-medium text-sm">Environment variables</Text>
          <Text color="gray" className="text-[13px]">
            Injected into the sandbox shell before the agent runs — useful for
            API keys or service tokens the agent needs. Standard{" "}
            <Text color="gray" className="font-medium text-[13px]">
              .env
            </Text>{" "}
            format: one{" "}
            <Text color="gray" className="font-medium text-[13px]">
              KEY=value
            </Text>{" "}
            per line. Existing values aren't shown back once saved; leave the
            field blank to keep them unchanged, or enter new values to replace
            them.
          </Text>
          <TextArea
            size="2"
            rows={4}
            value={form.environment_variables_text}
            onChange={(e) =>
              setForm((f) => ({
                ...f,
                environment_variables_text: e.target.value,
              }))
            }
            placeholder={
              editingEnv?.has_environment_variables
                ? "Environment variables are set. Enter new values to replace them."
                : "KEY=value"
            }
            color={envVarValidation.errors.length > 0 ? "red" : undefined}
            className="font-[var(--code-font-family)] [&_textarea]:text-xs"
          />
          {envVarValidation.errors.length > 0 && (
            <Flex direction="column" gap="0">
              {envVarValidation.errors.map((err) => (
                <Text key={err} color="red" className="text-[13px]">
                  {err}
                </Text>
              ))}
            </Flex>
          )}
        </Flex>

        <Flex justify="between" pt="2">
          {editingEnv ? (
            <Button
              color="red"
              variant="ghost"
              size="1"
              onClick={handleDelete}
              disabled={deleteMutation.isPending}
            >
              <Trash size={14} />
              Archive
            </Button>
          ) : (
            <div />
          )}
          <Flex gap="2">
            <Button color="gray" variant="outline" size="2" onClick={closeForm}>
              Cancel
            </Button>
            <Button
              size="2"
              onClick={handleSave}
              disabled={
                !form.name.trim() ||
                hasValidationErrors ||
                createMutation.isPending ||
                updateMutation.isPending
              }
            >
              {editingEnv ? "Save changes" : "Create environment"}
            </Button>
          </Flex>
        </Flex>
      </Flex>
    );
  }

  return (
    <Flex direction="column" gap="4">
      <Text color="gray" className="text-[13px]">
        A cloud environment is a sandbox profile for tasks that run remotely. It
        controls which outbound hosts the sandbox can reach and which
        environment variables — like API keys — are injected before the agent
        starts. Account-wide, so the same profile is available across all your
        projects. The built-in{" "}
        <Text color="gray" className="font-medium text-[13px]">
          Default
        </Text>{" "}
        uses full network access; create your own to lock things down or share
        secrets with the agent. Pick one in the Cloud section of the workspace
        picker when starting a task.
      </Text>
      <Flex justify="between" align="center">
        <Text className="font-medium text-[13px]">Environments</Text>
        <Button size="1" variant="outline" onClick={openCreate}>
          <Plus size={12} />
          New environment
        </Button>
      </Flex>

      {isLoading ? (
        <Text color="gray" className="text-[13px]">
          Loading environments...
        </Text>
      ) : environments.length === 0 ? (
        <Text color="gray" className="text-[13px]">
          No cloud environments configured yet. Create one to control network
          access for your cloud sessions.
        </Text>
      ) : (
        <Flex direction="column">
          {environments.map((env, i) => (
            <Flex
              key={env.id}
              align="center"
              justify="between"
              py="3"
              px="1"
              gap="3"
              style={{
                borderBottom:
                  i < environments.length - 1
                    ? "1px solid var(--gray-5)"
                    : undefined,
              }}
            >
              <Flex direction="column" gap="1" className="min-w-0 flex-1">
                <Text className="font-medium text-sm">{env.name}</Text>
                <Flex align="center" gap="2">
                  <Badge
                    size="1"
                    color={
                      env.network_access_level === "full"
                        ? "green"
                        : env.network_access_level === "trusted"
                          ? "blue"
                          : "orange"
                    }
                    variant="soft"
                  >
                    {env.network_access_level}
                  </Badge>
                  {env.network_access_level === "custom" &&
                    env.allowed_domains.length > 0 && (
                      <Text color="gray" className="text-[13px]">
                        {env.allowed_domains.length} domain
                        {env.allowed_domains.length !== 1 ? "s" : ""}
                      </Text>
                    )}
                  {customImagesEnabled &&
                    env.custom_image_id &&
                    env.custom_image_name && (
                      <Badge size="1" color="gray" variant="soft">
                        image: {env.custom_image_name}
                      </Badge>
                    )}
                </Flex>
              </Flex>
              <Button
                size="1"
                variant="ghost"
                color="gray"
                onClick={() => openEdit(env)}
                className="shrink-0"
              >
                <PencilSimple size={14} />
              </Button>
            </Flex>
          ))}
        </Flex>
      )}

      {customImagesEnabled && (
        <>
          <Flex justify="between" align="center" pt="2">
            <Text className="font-medium text-[13px]">Custom images</Text>
            <Button size="1" variant="outline" onClick={openCreateImage}>
              <Plus size={12} />
              New custom image
            </Button>
          </Flex>

          <Text color="gray" className="text-[13px]">
            A custom image is a sandbox base image with your own tools and
            dependencies pre-installed. Creating one starts a builder session
            where you describe what the image should include; once built, pick
            it as the base image of an environment.
          </Text>

          {imageForm && (
            <Flex
              direction="column"
              gap="3"
              p="3"
              className="rounded-2 border border-gray-6"
            >
              <Flex direction="column" gap="1">
                <Text className="font-medium text-sm">Name</Text>
                <TextField.Root
                  size="2"
                  value={imageForm?.name ?? ""}
                  onChange={(e) => patchImageForm({ name: e.target.value })}
                  placeholder="e.g. Playwright + Node 22"
                />
              </Flex>
              <Flex direction="column" gap="1">
                <Text className="font-medium text-sm">Description</Text>
                <TextArea
                  size="2"
                  rows={3}
                  value={imageForm?.description ?? ""}
                  onChange={(e) =>
                    patchImageForm({ description: e.target.value })
                  }
                  placeholder="What should this image include?"
                />
              </Flex>
              <Flex direction="column" gap="1">
                <Text className="font-medium text-sm">
                  Verify a repository (optional)
                </Text>
                <Text color="gray" className="text-[13px]">
                  The builder will make sure this repo's dependencies can be
                  brought up on the image.
                </Text>
                <div className="w-fit">
                  <GitHubRepoPicker
                    value={imageForm?.repository ?? null}
                    onChange={(repository) => patchImageForm({ repository })}
                    {...repoPickerProps}
                  />
                </div>
              </Flex>
              <Flex align="center" gap="2">
                <Checkbox
                  size="1"
                  checked={imageForm?.private ?? false}
                  onCheckedChange={(checked) =>
                    patchImageForm({ private: checked === true })
                  }
                />
                <Text color="gray" className="text-[13px]">
                  Only visible to me
                </Text>
              </Flex>
              <Flex gap="2" justify="end">
                <Button
                  color="gray"
                  variant="outline"
                  size="1"
                  onClick={() => setImageForm(null)}
                >
                  Cancel
                </Button>
                <Button
                  size="1"
                  onClick={handleCreateImage}
                  loading={createImageMutation.isPending}
                  disabled={
                    !imageForm?.name.trim() || createImageMutation.isPending
                  }
                >
                  Create image
                </Button>
              </Flex>
            </Flex>
          )}

          {images.length === 0 ? (
            !imageForm && (
              <Text color="gray" className="text-[13px]">
                No custom images yet. Create one to pre-install tools your cloud
                sessions need.
              </Text>
            )
          ) : (
            <Flex direction="column">
              {images.map((image, i) => {
                const inProgress = isImageBuildInProgress(image.status);
                const isFailed = isImageBuildFailed(image.status);
                const isBuildingThis =
                  buildMutation.isPending &&
                  buildMutation.variables?.id === image.id;
                const isEditingSpec = editingSpecImageId === image.id;
                const isViewingLog = viewingLogImageId === image.id;
                const hasBuildLog =
                  image.version > 0 ||
                  image.status === "ready" ||
                  image.status === "build_failed" ||
                  inProgress;
                return (
                  <Flex
                    key={image.id}
                    direction="column"
                    py="3"
                    px="1"
                    gap="2"
                    style={{
                      borderBottom:
                        i < images.length - 1
                          ? "1px solid var(--gray-5)"
                          : undefined,
                    }}
                  >
                    <Flex align="center" justify="between" gap="3">
                      <Flex
                        direction="column"
                        gap="1"
                        className="min-w-0 flex-1"
                      >
                        <Flex align="center" gap="1">
                          <Text className="font-medium text-sm">
                            {image.name}
                          </Text>
                          {image.private && (
                            <Lock size={12} className="shrink-0 text-gray-10" />
                          )}
                        </Flex>
                        <Flex align="center" gap="2">
                          <Badge
                            size="1"
                            color={IMAGE_STATUS_COLORS[image.status]}
                            variant="soft"
                          >
                            {image.status}
                          </Badge>
                          {image.version > 0 && (
                            <Text color="gray" className="text-[13px]">
                              v{image.version}
                            </Text>
                          )}
                          {image.repository && (
                            <Text color="gray" className="truncate text-[13px]">
                              {image.repository}
                            </Text>
                          )}
                        </Flex>
                        {isFailed && (
                          <Text color="red" className="text-[13px]">
                            {imageFailureDetail(image)}
                          </Text>
                        )}
                      </Flex>
                      <Flex align="center" gap="2" className="shrink-0">
                        <Button
                          size="1"
                          variant="ghost"
                          color="gray"
                          onClick={() => void handleOpenBuilder(image)}
                          loading={
                            builderTaskMutation.isPending &&
                            builderTaskMutation.variables === image.id
                          }
                          disabled={builderTaskMutation.isPending}
                        >
                          {image.status === "ready" ? "Update" : "Open builder"}
                        </Button>
                        <Button
                          size="1"
                          variant="ghost"
                          color="gray"
                          onClick={() => {
                            setEditingSpecImageId(image.id);
                            setSpecDraft(image.spec_yaml);
                          }}
                          disabled={inProgress || isEditingSpec}
                        >
                          Edit spec
                        </Button>
                        {hasBuildLog && (
                          <Button
                            size="1"
                            variant="ghost"
                            color="gray"
                            onClick={() =>
                              setViewingLogImageId(
                                isViewingLog ? null : image.id,
                              )
                            }
                          >
                            Build log
                          </Button>
                        )}
                        <Button
                          size="1"
                          variant="ghost"
                          onClick={() => buildMutation.mutate({ id: image.id })}
                          loading={isBuildingThis}
                          disabled={
                            inProgress ||
                            buildMutation.isPending ||
                            isEditingSpec
                          }
                        >
                          Save & build
                        </Button>
                        <Button
                          size="1"
                          variant="ghost"
                          color="gray"
                          onClick={() => openRenameImage(image)}
                          disabled={
                            deleteImageMutation.isPending ||
                            updateImageMutation.isPending
                          }
                        >
                          <PencilSimple size={14} />
                        </Button>
                        <Button
                          size="1"
                          variant="ghost"
                          color="red"
                          onClick={() => setDeleteConfirmImage(image)}
                          disabled={deleteImageMutation.isPending}
                        >
                          <Trash size={14} />
                        </Button>
                      </Flex>
                    </Flex>
                    {isEditingSpec && (
                      <Flex direction="column" gap="2">
                        <TextArea
                          size="2"
                          rows={10}
                          value={specDraft}
                          onChange={(e) => setSpecDraft(e.target.value)}
                          placeholder="Image spec (YAML)"
                          className="font-[var(--code-font-family)] [&_textarea]:text-xs"
                        />
                        <Flex gap="2" justify="end">
                          <Button
                            color="gray"
                            variant="outline"
                            size="1"
                            onClick={() => setEditingSpecImageId(null)}
                          >
                            Cancel
                          </Button>
                          <Button
                            size="1"
                            onClick={() => void handleSaveSpec(image)}
                            loading={isBuildingThis}
                            disabled={
                              inProgress ||
                              buildMutation.isPending ||
                              !specDraft.trim()
                            }
                          >
                            Save & build
                          </Button>
                        </Flex>
                      </Flex>
                    )}
                    {isViewingLog && (
                      <BuildLogPane
                        image={image}
                        onClose={() => setViewingLogImageId(null)}
                      />
                    )}
                  </Flex>
                );
              })}
            </Flex>
          )}

          <AlertDialog.Root
            open={deleteConfirmImage !== null}
            onOpenChange={(open) => {
              if (!open) setDeleteConfirmImage(null);
            }}
          >
            <AlertDialog.Content maxWidth="420px" size="1">
              <AlertDialog.Title className="text-sm">
                Delete custom image?
              </AlertDialog.Title>
              <AlertDialog.Description>
                <Text color="gray" className="text-[13px]">
                  Environments using "{deleteConfirmImage?.name}" fall back to
                  the default image.
                </Text>
              </AlertDialog.Description>
              <Flex justify="end" gap="3" mt="3">
                <AlertDialog.Cancel>
                  <Button variant="soft" color="gray" size="1">
                    Cancel
                  </Button>
                </AlertDialog.Cancel>
                <Button
                  variant="solid"
                  color="red"
                  size="1"
                  onClick={confirmDeleteImage}
                >
                  Delete
                </Button>
              </Flex>
            </AlertDialog.Content>
          </AlertDialog.Root>
          <AlertDialog.Root
            open={renameImage !== null}
            onOpenChange={(open) => {
              if (!open) setRenameImage(null);
            }}
          >
            <AlertDialog.Content maxWidth="420px" size="1">
              <AlertDialog.Title className="text-sm">
                Rename custom image
              </AlertDialog.Title>
              <AlertDialog.Description>
                <Text color="gray" className="text-[13px]">
                  Updates the display name. The build spec and status are
                  unchanged.
                </Text>
              </AlertDialog.Description>
              <Flex direction="column" gap="1" mt="3">
                <Text className="font-medium text-[13px]">Name</Text>
                <TextField.Root
                  size="2"
                  value={renameName}
                  onChange={(e) => setRenameName(e.target.value)}
                  placeholder="Image name"
                  autoFocus
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !updateImageMutation.isPending) {
                      e.preventDefault();
                      void handleRenameImage();
                    }
                  }}
                />
              </Flex>
              <Flex justify="end" gap="3" mt="3">
                <AlertDialog.Cancel>
                  <Button variant="soft" color="gray" size="1">
                    Cancel
                  </Button>
                </AlertDialog.Cancel>
                <Button
                  variant="solid"
                  size="1"
                  onClick={() => void handleRenameImage()}
                  loading={updateImageMutation.isPending}
                  disabled={
                    !renameName.trim() ||
                    renameName.trim() === renameImage?.name
                  }
                >
                  Save
                </Button>
              </Flex>
            </AlertDialog.Content>
          </AlertDialog.Root>
        </>
      )}
    </Flex>
  );
}
