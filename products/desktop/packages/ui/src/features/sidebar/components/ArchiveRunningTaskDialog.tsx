import { Warning } from "@phosphor-icons/react";
import { AlertDialog, Button, Flex, Text } from "@radix-ui/themes";
import { useState } from "react";

interface ArchiveRunningTaskDialogProps {
  open: boolean;
  taskTitle: string;
  stopsCloudSandbox: boolean;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}

export function ArchiveRunningTaskDialog({
  open,
  taskTitle,
  stopsCloudSandbox,
  onConfirm,
  onCancel,
}: ArchiveRunningTaskDialogProps) {
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async (event: React.MouseEvent) => {
    event.preventDefault();
    if (isSubmitting) return;
    setIsSubmitting(true);
    setError(null);
    try {
      await onConfirm();
    } catch (caughtError) {
      setError(
        caughtError instanceof Error
          ? caughtError.message
          : "Couldn't archive the task. Try again in a moment.",
      );
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <AlertDialog.Root
      open={open}
      onOpenChange={(isOpen) => {
        if (!isOpen && !isSubmitting) {
          setError(null);
          onCancel();
        }
      }}
    >
      <AlertDialog.Content maxWidth="420px" size="2">
        <AlertDialog.Title className="text-base">
          <Flex align="center" gap="2">
            <Warning size={18} weight="fill" color="var(--orange-9)" />
            Archive running task?
          </Flex>
        </AlertDialog.Title>
        <AlertDialog.Description className="text-sm">
          {taskTitle ? `"${taskTitle}"` : "This task"} is still running.
          {stopsCloudSandbox
            ? " Archiving it will stop its cloud run and shut down the sandbox."
            : " Archiving it now will stop the agent."}{" "}
          You can unarchive it later.
        </AlertDialog.Description>

        {error ? (
          <Text color="red" size="2" mt="2" as="div">
            {error}
          </Text>
        ) : null}

        <Flex justify="end" gap="2" mt="4">
          <AlertDialog.Cancel>
            <Button
              variant="soft"
              color="gray"
              size="1"
              disabled={isSubmitting}
            >
              Cancel
            </Button>
          </AlertDialog.Cancel>
          <AlertDialog.Action>
            <Button
              variant="solid"
              size="1"
              loading={isSubmitting}
              disabled={isSubmitting}
              onClick={handleConfirm}
            >
              Archive
            </Button>
          </AlertDialog.Action>
        </Flex>
      </AlertDialog.Content>
    </AlertDialog.Root>
  );
}
