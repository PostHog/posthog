import {
  isSkillButtonId,
  SKILL_BUTTON_ORDER,
  type SkillButtonId,
} from "@posthog/core/skill-buttons/catalog";
import { create } from "zustand";
import { persist } from "zustand/middleware";

interface SkillButtonsStoreState {
  lastSelectedId: SkillButtonId;
}

interface SkillButtonsStoreActions {
  setLastSelectedId: (id: SkillButtonId) => void;
}

type SkillButtonsStore = SkillButtonsStoreState & SkillButtonsStoreActions;

const DEFAULT_PRIMARY: SkillButtonId = SKILL_BUTTON_ORDER[0];

export const useSkillButtonsStore = create<SkillButtonsStore>()(
  persist(
    (set) => ({
      lastSelectedId: DEFAULT_PRIMARY,
      setLastSelectedId: (lastSelectedId) => set({ lastSelectedId }),
    }),
    {
      name: "skill-buttons-storage",
      merge: (persisted, current) => {
        const persistedState = persisted as {
          lastSelectedId?: string;
        };
        const restored = isSkillButtonId(persistedState.lastSelectedId)
          ? persistedState.lastSelectedId
          : DEFAULT_PRIMARY;
        return {
          ...current,
          lastSelectedId: restored,
        };
      },
    },
  ),
);
