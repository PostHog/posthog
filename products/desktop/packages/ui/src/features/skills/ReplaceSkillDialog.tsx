import {
  AlertDialog,
  AlertDialogClose,
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
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      <AlertDialogContent className="max-w-[420px]">
        <AlertDialogHeader>
          <AlertDialogTitle>Replace local skill</AlertDialogTitle>
          <AlertDialogDescription>
            A skill named "{skillName}" already exists in your skills. {verb}{" "}
            will replace your local version, including any edits.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogClose render={<Button variant="outline" />}>
            Cancel
          </AlertDialogClose>
          <AlertDialogClose
            render={
              <Button variant="destructive-outline" onClick={onConfirm} />
            }
          >
            Replace
          </AlertDialogClose>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
