import type { ReactNode } from "react";

export interface SelectorOption {
  id: string;
  label: string;
  description?: string;
  customInput?: boolean;
}

export interface StepInfo {
  label: string;
  completed?: boolean;
}

export interface StepAnswer {
  selectedIds: string[];
  customInput: string;
}

export interface ActionSelectorProps {
  title: ReactNode;
  pendingAction?: ReactNode;
  question: ReactNode;
  options: SelectorOption[];
  multiSelect?: boolean;
  allowCustomInput?: boolean;
  customInputPlaceholder?: string;
  currentStep?: number;
  steps?: StepInfo[];
  initialSelections?: string[];
  initialCustomInput?: string;
  hideSubmitButton?: boolean;
  onSelect: (optionId: string, customInput?: string) => void;
  onMultiSelect?: (optionIds: string[], customInput?: string) => void;
  onCancel?: () => void;
  onStepChange?: (stepIndex: number) => void;
  onStepAnswer?: (
    stepIndex: number,
    optionIds: string[],
    customInput?: string,
  ) => void;
}
