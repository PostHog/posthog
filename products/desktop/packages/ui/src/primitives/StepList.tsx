import {
  ArrowSquareOut,
  CheckCircle,
  Circle,
  XCircle,
} from "@phosphor-icons/react";
import { Button, Text } from "@posthog/quill";
import { Spinner } from "@posthog/ui/primitives/Spinner";
import { openExternalUrl } from "@posthog/ui/shell/openExternal";

export type StepStatus = "pending" | "in_progress" | "completed" | "failed";

export interface Step {
  key: string;
  label: string;
  status: StepStatus;
  detail?: string;
}

export function StepIcon({ status }: { status: StepStatus }) {
  switch (status) {
    case "in_progress":
      return <Spinner size="md" className="text-blue-9" />;
    case "completed":
      return <CheckCircle size={14} weight="fill" className="text-green-9" />;
    case "failed":
      return <XCircle size={14} weight="fill" className="text-red-9" />;
    default:
      return <Circle size={14} className="text-gray-8" />;
  }
}

function parseWebUrl(detail: string): URL | null {
  let parsed: URL;
  try {
    parsed = new URL(detail);
  } catch {
    return null;
  }
  return parsed.protocol === "https:" || parsed.protocol === "http:"
    ? parsed
    : null;
}

function formatWebUrl(url: URL): string {
  const path = url.pathname === "/" ? "" : url.pathname.replace(/\/$/, "");
  return `${url.host}${path}${url.search}`;
}

function StepDetail({ detail }: { detail: string }) {
  const url = parseWebUrl(detail);

  if (!url) {
    return <Text className="truncate text-[13px] text-gray-10">{detail}</Text>;
  }

  const label = formatWebUrl(url);
  return (
    <Button
      variant="link"
      size="sm"
      className="h-auto gap-1 p-0 text-[13px]"
      onClick={() => openExternalUrl(url.href)}
      title={url.href}
      aria-label={`Open ${label}`}
      data-attr="step-detail-link"
    >
      <span className="max-w-xs truncate">{label}</span>
      <ArrowSquareOut size={12} className="shrink-0" />
    </Button>
  );
}

interface StepRowProps {
  step: Step;
  size?: "1" | "2";
}

function StepRow({ step, size = "2" }: StepRowProps) {
  const sizeClass = size === "1" ? "text-[13px]" : "text-sm";
  return (
    <div className="flex flex-col">
      <div className="flex items-center gap-2">
        <StepIcon status={step.status} />
        <Text className={`${sizeClass} text-gray-12`}>{step.label}</Text>
      </div>
      {step.detail && (
        <div className="pl-6">
          <StepDetail detail={step.detail} />
        </div>
      )}
    </div>
  );
}

const GAP_CLASSES: Record<"1" | "2" | "3", string> = {
  "1": "gap-1",
  "2": "gap-2",
  "3": "gap-3",
};

interface StepListProps {
  steps: Step[];
  /** Text size for step labels. Default "2". */
  size?: "1" | "2";
  /** Gap between step rows. Default "1". */
  gap?: "1" | "2" | "3";
}

export function StepList({ steps, size = "2", gap = "1" }: StepListProps) {
  return (
    <div className={`flex flex-col ${GAP_CLASSES[gap]}`}>
      {steps.map((step) => (
        <StepRow key={step.key} step={step} size={size} />
      ))}
    </div>
  );
}
