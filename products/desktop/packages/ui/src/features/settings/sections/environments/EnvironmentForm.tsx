import { ArrowLeft, Trash } from "@phosphor-icons/react";
import {
  type Environment,
  slugifyEnvironmentName,
} from "@posthog/workspace-client/environment";
import { useWorkspaceTRPC } from "@posthog/workspace-client/trpc";
import { Button, Flex, Text, TextArea, TextField } from "@radix-ui/themes";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "../../../../primitives/toast";
import type { RegisteredFolder } from "../../../folders/types";

interface EnvironmentFormProps {
  folder: RegisteredFolder;
  environment?: Environment;
  onBack: () => void;
}

export function EnvironmentForm({
  folder,
  environment,
  onBack,
}: EnvironmentFormProps) {
  const trpc = useWorkspaceTRPC();
  const queryClient = useQueryClient();
  const createEnvironment = useMutation(
    trpc.environment.create.mutationOptions(),
  );
  const updateEnvironment = useMutation(
    trpc.environment.update.mutationOptions(),
  );
  const deleteEnvironment = useMutation(
    trpc.environment.delete.mutationOptions(),
  );
  const isNew = !environment;

  const [name, setName] = useState(environment?.name ?? folder.name);
  const [setupScript, setSetupScript] = useState(
    environment?.setup?.script ?? "",
  );
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);

  const slug = slugifyEnvironmentName(name.trim());
  const filename = slug ? `${slug}.toml` : "<name>.toml";
  const filePath = `${folder.path}/.posthog-code/environments/${filename}`;

  const handleSave = async () => {
    if (!name.trim()) {
      toast.error("Name is required");
      return;
    }

    setIsSaving(true);
    try {
      const setup = setupScript.trim()
        ? { script: setupScript.trim() }
        : undefined;

      if (isNew) {
        await createEnvironment.mutateAsync({
          repoPath: folder.path,
          name: name.trim(),
          setup,
        });
        toast.success("Environment created");
      } else {
        await updateEnvironment.mutateAsync({
          repoPath: folder.path,
          id: environment.id,
          name: name.trim(),
          setup,
        });
        toast.success("Environment updated");
      }

      await queryClient.invalidateQueries(trpc.environment.list.pathFilter());
      onBack();
    } catch {
      toast.error(`Failed to ${isNew ? "create" : "update"} environment`);
    } finally {
      setIsSaving(false);
    }
  };

  const handleDelete = async () => {
    if (isNew || !environment) return;
    const confirmed = window.confirm(
      `Delete environment "${environment.name}"? This will remove the TOML file from disk.`,
    );
    if (!confirmed) return;
    setIsDeleting(true);
    try {
      await deleteEnvironment.mutateAsync({
        repoPath: folder.path,
        id: environment.id,
      });
      toast.success("Environment deleted");
      await queryClient.invalidateQueries(trpc.environment.list.pathFilter());
      onBack();
    } catch {
      toast.error("Failed to delete environment");
    } finally {
      setIsDeleting(false);
    }
  };

  return (
    <Flex direction="column" gap="4">
      <button
        type="button"
        onClick={onBack}
        className="flex w-fit cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-[12px] text-gray-11 hover:text-gray-12"
      >
        <ArrowLeft size={10} />
        <span>Back to projects</span>
      </button>

      <Text className="font-medium text-[13px]">
        {isNew ? "Creating" : "Editing"} environment for {folder.name}
      </Text>

      <Flex direction="column" gap="1">
        <Text className="font-medium text-[13px]">Name</Text>
        <Text color="gray" className="text-[12px]">
          Shown in the worktree picker. Use short names like "default" or
          "with-seed-data" so you can spot which setup will run.
        </Text>
        <TextField.Root
          size="1"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Environment name"
          spellCheck={false}
        />
      </Flex>

      <Flex direction="column" gap="1">
        <Text className="font-medium text-[13px]">Setup script</Text>
        <Text color="gray" className="text-[12px]">
          Runs in the worktree root right after it's created, before the agent
          starts. Use it to install dependencies, generate build artifacts, or
          seed a local database. Leave blank if no setup is needed.
        </Text>
        <TextArea
          size="1"
          value={setupScript}
          onChange={(e) => setSetupScript(e.target.value)}
          placeholder={"# e.g.\npnpm install\npnpm run build"}
          rows={4}
          spellCheck={false}
          className="font-mono [&_textarea]:text-[11px]"
        />
      </Flex>

      {/* TODO: Actions UI disabled for now
      <Flex direction="column" gap="2">
        <Flex align="center" justify="between">
          <Text size="1" weight="medium">
            Actions
          </Text>
          <Button variant="outline" color="gray" size="1" onClick={handleAddAction}>
            <Plus size={10} />
            Add action
          </Button>
        </Flex>
        <Text size="1" color="gray" className="text-[12px]">
          Custom commands displayed in the task header.
        </Text>
      </Flex>
      */}

      <Text color="gray" className="text-[12px]">
        Environment will be stored at {filePath}
      </Text>

      <Flex justify="between">
        {!isNew ? (
          <Button
            size="1"
            variant="outline"
            color="red"
            onClick={handleDelete}
            disabled={isDeleting || isSaving}
          >
            <Trash size={12} />
            {isDeleting ? "Deleting..." : "Delete"}
          </Button>
        ) : (
          <div />
        )}
        <Button size="1" onClick={handleSave} disabled={isSaving || isDeleting}>
          {isSaving ? "Saving..." : "Save"}
        </Button>
      </Flex>
    </Flex>
  );
}
