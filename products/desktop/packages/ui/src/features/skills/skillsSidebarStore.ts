import { createSidebarStore } from "@posthog/ui/shell/createSidebarStore";

export const useSkillsSidebarStore = createSidebarStore({
  name: "skills-sidebar",
  defaultWidth: 380,
});
