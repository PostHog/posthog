import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Field,
  FieldDescription,
  FieldLabel,
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
    if (createSkill.isPending || !name.trim()) return;

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
      <DialogContent className="max-w-sm" showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>New skill</DialogTitle>
        </DialogHeader>
        <DialogBody viewportClassName="flex flex-col gap-4">
          <Field>
            <FieldLabel htmlFor="new-skill-name">Name</FieldLabel>
            <Input
              id="new-skill-name"
              autoFocus
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="my-skill"
              onKeyDown={(event) => {
                if (event.key === "Enter" && name.trim()) void handleCreate();
              }}
            />
            <FieldDescription>
              Lowercase letters, numbers, dashes, dots, and underscores
            </FieldDescription>
          </Field>
          <Field>
            <FieldLabel htmlFor="new-skill-location">Location</FieldLabel>
            <Select
              value={scope}
              onValueChange={(value) => setScope(value ?? USER_SCOPE)}
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
          </Field>
        </DialogBody>
        <DialogFooter>
          <DialogClose render={<Button type="button" variant="outline" />}>
            Cancel
          </DialogClose>
          <Button
            type="button"
            variant="primary"
            onClick={() => void handleCreate()}
            disabled={createSkill.isPending || !name.trim()}
            loading={createSkill.isPending}
          >
            Create
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
