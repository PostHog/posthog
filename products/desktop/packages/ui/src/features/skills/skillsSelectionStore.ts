import { create } from "zustand";

interface SkillsSelectionState {
  /**
   * A skill name another surface asked to open (by frontmatter `name`).
   * SkillsView consumes it once on load to select the matching skill, then
   * clears it so a later plain visit to /skills opens nothing.
   */
  requestedSkillName: string | null;
}

interface SkillsSelectionActions {
  requestSkill: (name: string) => void;
  clearRequestedSkill: () => void;
}

type SkillsSelectionStore = SkillsSelectionState & {
  actions: SkillsSelectionActions;
};

const useStore = create<SkillsSelectionStore>((set) => ({
  requestedSkillName: null,
  actions: {
    requestSkill: (name) => set({ requestedSkillName: name }),
    clearRequestedSkill: () => set({ requestedSkillName: null }),
  },
}));

export const useRequestedSkillName = () =>
  useStore((s) => s.requestedSkillName);
export const useSkillsSelectionActions = () => useStore((s) => s.actions);
