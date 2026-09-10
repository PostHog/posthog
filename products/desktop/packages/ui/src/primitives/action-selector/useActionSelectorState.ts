import type React from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  filterOtherOptions,
  isOtherOption,
  isSubmitOption,
  OTHER_OPTION_ID,
  SUBMIT_OPTION_ID,
} from "./constants";
import type { ActionSelectorProps, SelectorOption, StepAnswer } from "./types";

function needsCustomInput(option: SelectorOption): boolean {
  return option.customInput === true || isOtherOption(option.id);
}

function isInteractiveElementInDifferentCell(
  containerRef: React.RefObject<HTMLDivElement | null>,
): boolean {
  const el = document.activeElement;
  if (!(el instanceof HTMLElement)) return false;

  const isInteractive =
    el.tagName === "INPUT" ||
    el.tagName === "TEXTAREA" ||
    el.tagName === "SELECT" ||
    el.getAttribute("contenteditable") === "true";
  if (!isInteractive) return false;

  const activeCell = el.closest("[data-grid-cell]");
  const ownCell = containerRef.current?.closest("[data-grid-cell]");

  // Outside a grid (single-task mode): block focus steal from any interactive element.
  // Inside a grid: only block when the interactive element is in a different cell.
  if (!activeCell || !ownCell) return true;

  return activeCell !== ownCell;
}

interface UseActionSelectorStateProps {
  options: SelectorOption[];
  multiSelect: boolean;
  allowCustomInput: boolean;
  hideSubmitButton: boolean;
  currentStep: number;
  steps: ActionSelectorProps["steps"];
  initialSelections?: string[];
  initialCustomInput?: string;
  onSelect: ActionSelectorProps["onSelect"];
  onMultiSelect: ActionSelectorProps["onMultiSelect"];
  onStepChange: ActionSelectorProps["onStepChange"];
  onStepAnswer: ActionSelectorProps["onStepAnswer"];
}

export function useActionSelectorState({
  options,
  multiSelect,
  allowCustomInput,
  hideSubmitButton,
  currentStep,
  steps,
  initialSelections,
  initialCustomInput,
  onSelect,
  onMultiSelect,
  onStepChange,
  onStepAnswer,
}: UseActionSelectorStateProps) {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [checkedOptions, setCheckedOptions] = useState<Set<string>>(() =>
    initialSelections?.length ? new Set(initialSelections) : new Set(),
  );
  const [customInput, setCustomInput] = useState(initialCustomInput ?? "");
  const [isEditing, setIsEditing] = useState(false);
  const [internalStep, setInternalStep] = useState(currentStep);
  const [stepAnswers, setStepAnswers] = useState<Map<number, StepAnswer>>(
    () => new Map(),
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const prevActiveStepRef = useRef(currentStep);
  const customInputRef = useRef("");
  customInputRef.current = customInput;

  const activeStep = internalStep;
  const hasSteps = steps !== undefined && steps.length > 1;
  const numSteps = steps?.length ?? 0;
  const showSubmitButton = !hideSubmitButton && (multiSelect || hasSteps);

  const allOptions = useMemo(() => {
    const opts = allowCustomInput
      ? [...options, { id: OTHER_OPTION_ID, label: "Other", description: "" }]
      : options;
    if (showSubmitButton) {
      return [
        ...opts,
        { id: SUBMIT_OPTION_ID, label: "Submit", description: "" },
      ];
    }
    return opts;
  }, [options, allowCustomInput, showSubmitButton]);

  const numOptions = allOptions.length;
  const selectedOption = allOptions[selectedIndex];
  const showInlineEdit =
    isEditing && selectedOption && needsCustomInput(selectedOption);
  const canSubmitOrAdvance = checkedOptions.size > 0;

  // Options can change while mounted (a consumer adding/removing a choice);
  // clamp so the highlight and Enter never reference past the end of the list.
  useEffect(() => {
    setSelectedIndex((i) => Math.min(i, Math.max(0, numOptions - 1)));
  }, [numOptions]);

  useEffect(() => {
    if (!isInteractiveElementInDifferentCell(containerRef)) {
      containerRef.current?.focus();
    }
  }, []);

  useEffect(() => {
    setInternalStep(currentStep);
  }, [currentStep]);

  const setStep = useCallback(
    (nextStep: number) => {
      if (nextStep === activeStep) return;
      onStepChange?.(nextStep);
      setInternalStep(nextStep);
    },
    [activeStep, onStepChange],
  );

  const saveCurrentStepAnswer = useCallback(() => {
    const checkedIds = Array.from(checkedOptions);
    const answer: StepAnswer = {
      selectedIds: checkedIds,
      customInput,
    };
    setStepAnswers((prev) => {
      const next = new Map(prev);
      next.set(activeStep, answer);
      return next;
    });
    onStepAnswer?.(activeStep, checkedIds, customInput.trim() || undefined);
  }, [activeStep, checkedOptions, customInput, onStepAnswer]);

  const restoreStepAnswer = useCallback(
    (step: number, { autoFocus = true }: { autoFocus?: boolean } = {}) => {
      const saved = stepAnswers.get(step);
      if (saved) {
        setCheckedOptions(new Set(saved.selectedIds));
        setCustomInput(saved.customInput);
      } else if (initialSelections?.length || initialCustomInput) {
        setCheckedOptions(new Set(initialSelections ?? []));
        setCustomInput(initialCustomInput ?? "");
      } else {
        setCheckedOptions(new Set());
        setCustomInput("");
      }
      setSelectedIndex(0);
      setIsEditing(false);
      if (autoFocus) {
        containerRef.current?.focus();
      }
    },
    [initialSelections, initialCustomInput, stepAnswers],
  );

  useEffect(() => {
    if (activeStep === prevActiveStepRef.current) return;
    prevActiveStepRef.current = activeStep;
    restoreStepAnswer(activeStep, {
      autoFocus: !isInteractiveElementInDifferentCell(containerRef),
    });
  }, [activeStep, restoreStepAnswer]);

  useEffect(() => {
    const isCustom = !!selectedOption && needsCustomInput(selectedOption);
    setIsEditing(isCustom);
    if (isCustom && showSubmitButton && customInputRef.current.trim()) {
      setCheckedOptions((prev) => {
        if (prev.has(selectedOption.id)) return prev;
        const next = multiSelect ? new Set(prev) : new Set<string>();
        next.add(selectedOption.id);
        return next;
      });
    }
  }, [selectedOption, showSubmitButton, multiSelect]);

  const moveUp = useCallback(() => {
    setHoveredIndex(null);
    setSelectedIndex((prev) => (prev > 0 ? prev - 1 : numOptions - 1));
  }, [numOptions]);

  const moveDown = useCallback(() => {
    setHoveredIndex(null);
    setSelectedIndex((prev) => (prev < numOptions - 1 ? prev + 1 : 0));
  }, [numOptions]);

  const moveToPrevStep = useCallback(() => {
    if (!hasSteps) return;
    saveCurrentStepAnswer();
    const prevStep = activeStep > 0 ? activeStep - 1 : numSteps - 1;
    setStep(prevStep);
  }, [hasSteps, activeStep, numSteps, saveCurrentStepAnswer, setStep]);

  const moveToNextStep = useCallback(() => {
    if (!hasSteps) return;
    saveCurrentStepAnswer();
    const nextStep = activeStep < numSteps - 1 ? activeStep + 1 : 0;
    setStep(nextStep);
  }, [hasSteps, activeStep, numSteps, saveCurrentStepAnswer, setStep]);

  const toggleCheck = useCallback(
    (optionId: string) => {
      setCheckedOptions((prev) => {
        const next = new Set(prev);
        if (multiSelect) {
          if (next.has(optionId)) {
            next.delete(optionId);
          } else {
            next.add(optionId);
          }
        } else {
          if (next.has(optionId)) {
            next.clear();
          } else {
            next.clear();
            next.add(optionId);
          }
        }
        return next;
      });
    },
    [multiSelect],
  );

  const handleSubmitMulti = useCallback(() => {
    const ids = Array.from(checkedOptions);
    if (ids.length === 0) return;
    const hasOther = ids.some(isOtherOption);
    const filteredIds = filterOtherOptions(ids);
    if (hasOther && customInput.trim()) {
      onMultiSelect?.(filteredIds, customInput.trim());
    } else {
      onMultiSelect?.(filteredIds);
    }
  }, [checkedOptions, customInput, onMultiSelect]);

  const handleSubmitSingle = useCallback(() => {
    const checkedId = Array.from(checkedOptions)[0];
    if (!checkedId) return;
    if (isOtherOption(checkedId) && customInput.trim()) {
      onSelect(checkedId, customInput.trim());
    } else {
      onSelect(checkedId);
    }
  }, [checkedOptions, customInput, onSelect]);

  const selectCurrent = useCallback(() => {
    const selected = allOptions[selectedIndex];

    if (isSubmitOption(selected.id)) {
      if (!showSubmitButton) {
        onSelect(selected.id);
        return;
      }
      if (!canSubmitOrAdvance) return;
      if (hasSteps && activeStep < numSteps - 1) {
        saveCurrentStepAnswer();
        setStep(activeStep + 1);
      } else {
        if (multiSelect) {
          handleSubmitMulti();
        } else {
          handleSubmitSingle();
        }
      }
      return;
    }

    if (showSubmitButton) {
      if (needsCustomInput(selected) && !isEditing) {
        if (!multiSelect) {
          setCheckedOptions(new Set());
        }
        setIsEditing(true);
      } else {
        toggleCheck(selected.id);
      }
    } else if (needsCustomInput(selected)) {
      if (customInput.trim()) {
        onSelect(selected.id, customInput.trim());
      }
    } else {
      onSelect(selected.id);
    }
  }, [
    allOptions,
    selectedIndex,
    hasSteps,
    activeStep,
    numSteps,
    multiSelect,
    handleSubmitMulti,
    handleSubmitSingle,
    showSubmitButton,
    toggleCheck,
    customInput,
    onSelect,
    saveCurrentStepAnswer,
    setStep,
    isEditing,
    canSubmitOrAdvance,
  ]);

  const selectByIndex = useCallback(
    (index: number) => {
      if (index < 0 || index >= allOptions.length) return;
      const selected = allOptions[index];

      if (isSubmitOption(selected.id)) {
        if (!showSubmitButton) {
          onSelect(selected.id);
          return;
        }
        if (!canSubmitOrAdvance) return;
        if (hasSteps && activeStep < numSteps - 1) {
          saveCurrentStepAnswer();
          setStep(activeStep + 1);
        } else {
          if (multiSelect) {
            handleSubmitMulti();
          } else {
            handleSubmitSingle();
          }
        }
        return;
      }

      if (showSubmitButton) {
        toggleCheck(selected.id);
      } else if (needsCustomInput(selected)) {
        setIsEditing(true);
      } else {
        onSelect(selected.id);
      }
    },
    [
      allOptions,
      hasSteps,
      activeStep,
      numSteps,
      multiSelect,
      handleSubmitMulti,
      handleSubmitSingle,
      showSubmitButton,
      toggleCheck,
      onSelect,
      saveCurrentStepAnswer,
      setStep,
      canSubmitOrAdvance,
    ],
  );

  const handleClick = useCallback(
    (index: number) => {
      if (index < 0 || index >= allOptions.length) return;
      setSelectedIndex(index);
      setHoveredIndex(null);
      const selected = allOptions[index];

      if (isSubmitOption(selected.id)) {
        if (!showSubmitButton) {
          onSelect(selected.id);
          return;
        }
        if (!canSubmitOrAdvance) return;
        if (hasSteps && activeStep < numSteps - 1) {
          saveCurrentStepAnswer();
          setStep(activeStep + 1);
        } else {
          if (multiSelect) {
            handleSubmitMulti();
          } else {
            handleSubmitSingle();
          }
        }
        return;
      }

      if (showSubmitButton) {
        if (needsCustomInput(selected)) {
          if (!multiSelect) {
            setCheckedOptions(new Set());
          }
          setIsEditing(true);
        } else {
          toggleCheck(selected.id);
        }
      } else if (needsCustomInput(selected)) {
        setIsEditing(true);
      } else {
        onSelect(selected.id);
      }
    },
    [
      allOptions,
      hasSteps,
      activeStep,
      numSteps,
      multiSelect,
      handleSubmitMulti,
      handleSubmitSingle,
      showSubmitButton,
      toggleCheck,
      onSelect,
      saveCurrentStepAnswer,
      setStep,
      canSubmitOrAdvance,
    ],
  );

  const handleStepClick = useCallback(
    (stepIndex: number) => {
      saveCurrentStepAnswer();
      setStep(stepIndex);
    },
    [saveCurrentStepAnswer, setStep],
  );

  const handleEscape = useCallback(() => {
    setCustomInput("");
    setIsEditing(false);
    containerRef.current?.focus();
  }, []);

  const handleCustomInputChange = useCallback(
    (value: string) => {
      setCustomInput(value);
      if (
        showSubmitButton &&
        selectedOption &&
        needsCustomInput(selectedOption)
      ) {
        setCheckedOptions((prev) => {
          const next = new Set(prev);
          if (value.trim()) {
            if (!prev.has(selectedOption.id)) {
              if (!multiSelect) {
                next.clear();
              }
              next.add(selectedOption.id);
            }
          } else {
            next.delete(selectedOption.id);
          }
          return next;
        });
      }
    },
    [showSubmitButton, selectedOption, multiSelect],
  );

  const ensureChecked = useCallback((optionId: string) => {
    setCheckedOptions((prev) => {
      if (prev.has(optionId)) return prev;
      const next = new Set(prev);
      next.add(optionId);
      return next;
    });
  }, []);

  const handleInlineSubmit = useCallback(() => {
    if (!selectedOption) return;
    const trimmed = customInput.trim();

    if (!showSubmitButton) {
      if (trimmed) {
        onSelect(selectedOption.id, trimmed);
      }
      return;
    }

    if (trimmed) {
      ensureChecked(selectedOption.id);
    }
    setIsEditing(false);

    if (!trimmed && !canSubmitOrAdvance) {
      containerRef.current?.focus();
      return;
    }

    if (hasSteps && activeStep < numSteps - 1) {
      saveCurrentStepAnswer();
      setStep(activeStep + 1);
      containerRef.current?.focus();
      return;
    }

    if (multiSelect) {
      handleSubmitMulti();
    } else {
      handleSubmitSingle();
    }
  }, [
    showSubmitButton,
    ensureChecked,
    selectedOption,
    customInput,
    onSelect,
    hasSteps,
    activeStep,
    numSteps,
    saveCurrentStepAnswer,
    setStep,
    multiSelect,
    handleSubmitMulti,
    handleSubmitSingle,
    canSubmitOrAdvance,
  ]);

  const handleNavigateUp = useCallback(() => {
    if (
      selectedOption &&
      needsCustomInput(selectedOption) &&
      customInput.trim() &&
      showSubmitButton
    ) {
      ensureChecked(selectedOption.id);
    }
    containerRef.current?.focus();
    moveUp();
  }, [moveUp, selectedOption, customInput, showSubmitButton, ensureChecked]);

  const handleNavigateDown = useCallback(() => {
    if (
      selectedOption &&
      needsCustomInput(selectedOption) &&
      customInput.trim() &&
      showSubmitButton
    ) {
      ensureChecked(selectedOption.id);
    }
    containerRef.current?.focus();
    moveDown();
  }, [moveDown, selectedOption, customInput, showSubmitButton, ensureChecked]);

  return {
    selectedIndex,
    setSelectedIndex,
    hoveredIndex,
    setHoveredIndex,
    checkedOptions,
    customInput,
    setCustomInput: handleCustomInputChange,
    isEditing,
    activeStep,
    stepAnswers,
    containerRef,
    hasSteps,
    numSteps,
    showSubmitButton,
    canSubmitOrAdvance,
    allOptions,
    selectedOption,
    showInlineEdit,
    moveUp,
    moveDown,
    moveToPrevStep,
    moveToNextStep,
    selectCurrent,
    selectByIndex,
    handleClick,
    handleStepClick,
    handleEscape,
    handleInlineSubmit,
    handleNavigateUp,
    handleNavigateDown,
    handleSubmitMulti,
    handleSubmitSingle,
  };
}
