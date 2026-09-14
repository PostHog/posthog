import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@posthog/quill";
import { toast } from "@posthog/ui/primitives/toast";
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
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[380px]">
        <DialogHeader>
          <DialogTitle>New skill</DialogTitle>
        </DialogHeader>
        <DialogBody>
          <div className="flex flex-col gap-3">
            <div>
              <label
                htmlFor="new-skill-name"
                className="mb-1 block text-(--gray-10) text-xs"
              >
                Name
              </label>
              <Input
                id="new-skill-name"
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="my-skill"
                onKeyDown={(e) => {
                  if (e.key === "Enter" && name.trim()) void handleCreate();
                }}
              />
              <p className="mt-1 text-(--gray-9) text-xs">
                Lowercase letters, numbers, dashes, dots, and underscores
              </p>
            </div>
            <div>
              <label
                htmlFor="new-skill-location"
                className="mb-1 block text-(--gray-10) text-xs"
              >
                Location
              </label>
              <Select
                value={scope}
                onValueChange={(value: string | null) => {
                  if (value) setScope(value);
                }}
                items={[
                  { value: USER_SCOPE, label: "Your skills" },
                  ...folders.map((folder) => ({
                    value: folder.path,
                    label: `Repository: ${folder.name}`,
                  })),
                ]}
              >
                <SelectTrigger id="new-skill-location" className="w-full">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={USER_SCOPE}>Your skills</SelectItem>
                  {folders.map((folder) => (
                    <SelectItem key={folder.path} value={folder.path}>
                      Repository: {folder.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </DialogBody>
        <DialogFooter>
          <DialogClose render={<Button size="sm" variant="outline" />}>
            Cancel
          </DialogClose>
          <Button
            size="sm"
            variant="primary"
            onClick={() => void handleCreate()}
            loading={createSkill.isPending}
            disabled={createSkill.isPending || !name.trim()}
          >
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
