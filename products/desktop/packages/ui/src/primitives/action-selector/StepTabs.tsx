import { Box, Flex, Text } from "@radix-ui/themes";
import type { StepAnswer, StepInfo } from "./types";

interface StepTabsProps {
  steps: StepInfo[];
  activeStep: number;
  stepAnswers: Map<number, StepAnswer>;
  onStepClick: (stepIndex: number) => void;
}

export function StepTabs({
  steps,
  activeStep,
  stepAnswers,
  onStepClick,
}: StepTabsProps) {
  return (
    <Flex align="center" gap="2">
      {steps.map((step, i) => {
        const isCurrent = i === activeStep;
        const savedAnswer = stepAnswers.get(i);
        const hasActualAnswer =
          savedAnswer !== undefined &&
          (savedAnswer.selectedIds.length > 0 ||
            savedAnswer.customInput.trim() !== "");
        const isCompleted = step.completed || hasActualAnswer;

        return (
          <Box
            key={step.label}
            py="1"
            px="2"
            onClick={() => onStepClick(i)}
            style={{
              background: isCurrent ? "var(--blue-3)" : "transparent",
            }}
            className="cursor-pointer rounded-(--radius-2)"
          >
            <Text
              className={`text-[13px] ${
                isCurrent
                  ? "font-medium text-blue-11"
                  : isCompleted
                    ? "text-green-11"
                    : "text-gray-11"
              }`}
            >
              {isCompleted && "✓ "}
              {step.label}
            </Text>
          </Box>
        );
      })}
    </Flex>
  );
}
