import type {
  SupportTicket,
  SupportTicketMessage,
} from "@posthog/api-client/posthog-client";
import {
  buildTicketAgentPrompt,
  readTicketTaskId,
  withTicketTaskId,
} from "@posthog/core/support/ticketTaskLink";
import { getErrorTitle } from "@posthog/core/task-detail/taskInput";
import {
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import { toastError } from "@posthog/ui/features/notifications/errorDetails";
import { useUpdateSupportTicket } from "@posthog/ui/features/support/hooks/useUpdateSupportTicket";
import { useCreateTask } from "@posthog/ui/features/tasks/useTaskCrudMutations";
import { useCallback, useState } from "react";

// An ordinary Desktop task, linked to the ticket only once it exists.
export function useTicketAgentThread(ticket: SupportTicket | undefined) {
  const taskService = useService<TaskService>(TASK_SERVICE);
  const { invalidateTasks } = useCreateTask();
  const updateTicket = useUpdateSupportTicket();
  const [isStarting, setIsStarting] = useState(false);

  const taskId = ticket ? readTicketTaskId(ticket.tags) : null;

  const startThread = useCallback(
    async (request: string, messages: readonly SupportTicketMessage[]) => {
      if (!ticket || isStarting) {
        return;
      }

      setIsStarting(true);
      try {
        const result = await taskService.createTask(
          {
            content: buildTicketAgentPrompt(ticket, messages, request),
            taskDescription: `Support ticket #${ticket.ticket_number}`,
          },
          (output) => invalidateTasks(output.task),
        );

        if (!result.success) {
          toastError(getErrorTitle(result.failedStep), result.error);
          return;
        }

        updateTicket.mutate({
          ticketId: ticket.id,
          updates: { tags: withTicketTaskId(ticket.tags, result.data.task.id) },
        });
      } catch (error) {
        toastError("Could not start the agent thread", error);
      } finally {
        setIsStarting(false);
      }
    },
    [ticket, isStarting, taskService, invalidateTasks, updateTicket],
  );

  return { taskId, startThread, isStarting };
}
