import type { TourDefinition } from "@posthog/core/tour/types";
import { hoggiePng } from "@posthog/shared/hoggies";

export const createFirstTaskTour: TourDefinition = {
  id: "create-first-task",
  completeForReturningUsers: true,
  steps: [
    {
      id: "folder-picker",
      target: "folder-picker",
      hogSrc: hoggiePng("office-worker")!,
      message: "Pick a repo to work with. This tells me where your code lives!",
      advanceOn: { type: "action" },
    },
    {
      id: "task-editor",
      target: "task-input-editor",
      hogSrc: hoggiePng("traffic-controller")!,
      message:
        "Describe what you want to build or fix. Be as specific as you like!",
      advanceOn: { type: "action" },
    },
    {
      id: "submit-button",
      target: "task-input-submit",
      hogSrc: hoggiePng("rocket")!,
      message: "Hit send or press Enter to launch your first agent!",
      advanceOn: { type: "click" },
    },
  ],
};
