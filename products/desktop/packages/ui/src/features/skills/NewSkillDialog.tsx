import { toast } from "@posthog/ui/primitives/toast";
import {
  Box,
  Button,
  Dialog,
  Flex,
  Select,
  Text,
  TextField,
} from "@radix-ui/themes";
import { useState } from "react";
import { useFolders } from "../folders/useFolders";
import { skillErrorDescription } from "./skillErrors";
import { useCreateSkill } from "./useSkillMutations";

const USER_SCOPE = "user";

interface NewSkillDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCreated: (path: string) => void;
}

export function NewSkillDialog({
  open,
  onOpenChange,
  onCreated,
}: NewSkillDialogProps) {
  const { folders } = useFolders();
  const createSkill = useCreateSkill();
  const [name, setName] = useState("");
  const [scope, setScope] = useState(USER_SCOPE);

  const handleCreate = async () => {
    try {
      const result = await createSkill.mutateAsync(
        scope === USER_SCOPE
          ? { scope: "user", name }
          : { scope: "repo", repoPath: scope, name },
      );
      setName("");
      onOpenChange(false);
      onCreated(result.path);
    } catch (error) {
      toast.error("Failed to create skill", {
        description: skillErrorDescription(error),
      });
    }
  };

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content maxWidth="380px" size="2">
        <Dialog.Title size="3">New skill</Dialog.Title>
        <Flex direction="column" gap="3" mt="3">
          <Box>
            <Text className="mb-1 block text-[12px] text-gray-10">Name</Text>
            <TextField.Root
              size="2"
              autoFocus
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my-skill"
              onKeyDown={(e) => {
                if (e.key === "Enter" && name.trim()) void handleCreate();
              }}
            />
            <Text className="mt-1 block text-[11px] text-gray-9">
              Lowercase letters, numbers, dashes, dots, and underscores
            </Text>
          </Box>
          <Box>
            <Text className="mb-1 block text-[12px] text-gray-10">
              Location
            </Text>
            <Select.Root value={scope} onValueChange={setScope}>
              <Select.Trigger className="w-full" />
              <Select.Content>
                <Select.Item value={USER_SCOPE}>Your skills</Select.Item>
                {folders.map((folder) => (
                  <Select.Item key={folder.path} value={folder.path}>
                    Repository: {folder.name}
                  </Select.Item>
                ))}
              </Select.Content>
            </Select.Root>
          </Box>
          <Flex justify="end" gap="2" mt="2">
            <Dialog.Close>
              <Button size="1" variant="soft" color="gray">
                Cancel
              </Button>
            </Dialog.Close>
            <Button
              size="1"
              variant="solid"
              onClick={handleCreate}
              disabled={createSkill.isPending || !name.trim()}
            >
              Create
            </Button>
          </Flex>
        </Flex>
      </Dialog.Content>
    </Dialog.Root>
  );
}
