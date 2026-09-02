import { Box } from "@radix-ui/themes";
import { ActionTerminal } from "../../terminal/ActionTerminal";

interface ActionPanelProps {
  taskId: string;
  actionId: string;
  command: string;
  cwd: string;
}

export function ActionPanel({
  taskId,
  actionId,
  command,
  cwd,
}: ActionPanelProps) {
  return (
    <Box height="100%">
      <ActionTerminal
        actionId={actionId}
        command={command}
        cwd={cwd}
        taskId={taskId}
      />
    </Box>
  );
}
