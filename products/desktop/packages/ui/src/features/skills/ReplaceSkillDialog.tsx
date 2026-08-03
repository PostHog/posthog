import { AlertDialog, Button, Flex } from "@radix-ui/themes";

interface ReplaceSkillDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  skillName: string;
  /** Leads the warning sentence, e.g. "Reinstalling" or "Importing". */
  verb: string;
  onConfirm: () => void;
}

/** Confirm-overwrite dialog shared by every install/import surface. */
export function ReplaceSkillDialog({
  open,
  onOpenChange,
  skillName,
  verb,
  onConfirm,
}: ReplaceSkillDialogProps) {
  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Content maxWidth="420px" size="2">
        <AlertDialog.Title size="3">Replace local skill</AlertDialog.Title>
        <AlertDialog.Description size="1">
          A skill named "{skillName}" already exists in your skills. {verb} will
          replace your local version, including any edits.
        </AlertDialog.Description>
        <Flex justify="end" gap="2" mt="4">
          <AlertDialog.Cancel>
            <Button size="1" variant="soft" color="gray">
              Cancel
            </Button>
          </AlertDialog.Cancel>
          <AlertDialog.Action>
            <Button size="1" variant="solid" color="red" onClick={onConfirm}>
              Replace
            </Button>
          </AlertDialog.Action>
        </Flex>
      </AlertDialog.Content>
    </AlertDialog.Root>
  );
}
