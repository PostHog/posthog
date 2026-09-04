import { Text } from "@posthog/quill";
import type { ReactNode } from "react";

interface StepBodyProps {
  title: string;
  description: string;
  children: ReactNode;
}

/** A step's heading and its content, so every step reads the same way. */
export function StepBody({ title, description, children }: StepBodyProps) {
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <Text className="font-medium text-(--gray-12) text-[13px]">
          {title}
        </Text>
        <Text className="max-w-[56ch] text-(--gray-11) text-[12px] leading-snug">
          {description}
        </Text>
      </div>
      {children}
    </div>
  );
}
