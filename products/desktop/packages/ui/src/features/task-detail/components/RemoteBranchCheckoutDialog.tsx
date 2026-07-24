import { GitBranch } from "@phosphor-icons/react";
import { AlertDialog, Button, Code, Flex } from "@radix-ui/themes";
import { useRemoteBranchConfirmStore } from "../stores/remoteBranchConfirmStore";

/**
 * Globally-mounted confirmation shown when a user starts a worktree task on a
 * branch that exists only on the remote. Confirming fetches the branch and
 * checks it out locally into the new worktree.
 */
export function RemoteBranchCheckoutDialog() {
  const isOpen = useRemoteBranchConfirmStore((s) => s.isOpen);
  const branch = useRemoteBranchConfirmStore((s) => s.branch);
  const accept = useRemoteBranchConfirmStore((s) => s.accept);
  const cancel = useRemoteBranchConfirmStore((s) => s.cancel);

  return (
    <AlertDialog.Root
      open={isOpen}
      onOpenChange={(open) => {
        if (!open) cancel();
      }}
    >
      <AlertDialog.Content maxWidth="440px" size="2">
        <AlertDialog.Title className="text-base">
          <Flex align="center" gap="2">
            <GitBranch size={18} weight="bold" color="var(--accent-9)" />
            Check out remote branch?
          </Flex>
        </AlertDialog.Title>
        <AlertDialog.Description className="text-sm">
          {branch ? <Code>{branch}</Code> : "This branch"} doesn't exist locally
          but was found on the remote. Check it out into a new worktree to
          continue working on it?
        </AlertDialog.Description>

        <Flex justify="end" gap="2" mt="4">
          <AlertDialog.Cancel>
            <Button variant="soft" color="gray" size="1">
              Cancel
            </Button>
          </AlertDialog.Cancel>
          <AlertDialog.Action>
            <Button variant="solid" size="1" onClick={accept}>
              Check out branch
            </Button>
          </AlertDialog.Action>
        </Flex>
      </AlertDialog.Content>
    </AlertDialog.Root>
  );
}
