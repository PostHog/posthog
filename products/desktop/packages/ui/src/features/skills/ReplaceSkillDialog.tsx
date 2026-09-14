import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";

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
    <AlertDialog open={open} onOpenChange={() => undefined}>
      <AlertDialogContent className="max-w-[420px]">
        <AlertDialogHeader>
          <AlertDialogTitle>Replace local skill</AlertDialogTitle>
          <AlertDialogDescription>
            A skill named "{skillName}" already exists in your skills. {verb}
            will replace your local version, including any edits.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant="destructive-outline"
            onClick={() => {
              onConfirm();
              onOpenChange(false);
            }}
          >
            Replace
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
