import { ArrowSquareOut, MagnifyingGlass } from "@phosphor-icons/react";
import {
  type EnvironmentSetupPlan,
  stepError,
  withToolToggled,
} from "@posthog/core/settings/environmentSetup";
import {
  IMAGE_PRESET_TOOLS,
  IMAGE_TOOL_CATEGORIES,
  type ImagePresetTool,
  isDirectlyInstallable,
  toolInstallMethod,
  toolsSizeMb,
} from "@posthog/core/settings/imagePreset";
import {
  Checkbox,
  Input,
  Text,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { StepBody } from "@posthog/ui/features/settings/sections/environments/setup/StepBody";
import { useId, useState } from "react";

const TOOLTIP_DELAY_MS = 400;

interface ToolsStepProps {
  plan: EnvironmentSetupPlan;
  onChange: (plan: EnvironmentSetupPlan) => void;
}

/**
 * The tools the image carries, grouped by what they are for, with the size and
 * install method each one adds so a long list's cost on the image is visible.
 */
export function ToolsStep({ plan, onChange }: ToolsStepProps) {
  const [query, setQuery] = useState("");
  const searchId = useId();
  const all = IMAGE_PRESET_TOOLS;
  const error = stepError(plan, "tools");
  const needle = query.trim().toLowerCase();
  const matches = (tool: ImagePresetTool) =>
    needle === "" ||
    tool.command.toLowerCase().includes(needle) ||
    tool.name.toLowerCase().includes(needle) ||
    tool.reason.toLowerCase().includes(needle);
  const visible = all.filter(matches);
  const picked = all.filter((tool) => !plan.excludedToolIds.includes(tool.id));

  return (
    <StepBody
      title="Tools on the image"
      description="Tools an agent reaches for on most runs; each one is listed with the reason it is here"
    >
      <div className="flex w-full items-center gap-3">
        <div className="relative flex-1">
          <MagnifyingGlass
            size={12}
            aria-hidden="true"
            className="-translate-y-1/2 absolute top-1/2 left-2.5 text-(--gray-10)"
          />
          <Input
            id={searchId}
            className="h-7 pl-7 text-[12px]"
            value={query}
            placeholder="Search tools"
            aria-label="Search tools"
            data-attr="environment-setup-tool-search"
            onChange={(event) => setQuery(event.target.value)}
          />
        </div>
        <Text className="shrink-0 text-(--gray-10) text-[11.5px] tabular-nums">
          {picked.length} of {all.length} selected, about {toolsSizeMb(picked)}{" "}
          MB
        </Text>
      </div>

      {visible.length === 0 ? (
        <Text className="text-(--gray-11) text-[12px]">
          No tool matches "{query.trim()}". A builder session can install
          anything else you name.
        </Text>
      ) : (
        <div className="relative max-h-[360px] w-full overflow-y-auto rounded-(--radius-3) border border-border">
          <TooltipProvider delay={TOOLTIP_DELAY_MS}>
            {IMAGE_TOOL_CATEGORIES.map((category) => {
              const tools = visible.filter(
                (tool) => tool.category === category.id,
              );
              if (tools.length === 0) return null;
              return (
                <section key={category.id}>
                  <h4 className="sticky top-0 z-10 border-(--gray-4) border-y bg-(--gray-2) px-3 py-1 font-medium text-(--gray-11) text-[10.5px] uppercase tracking-wide">
                    {category.label}
                  </h4>
                  {tools.map((tool) => (
                    <ToolRow
                      key={tool.id}
                      tool={tool}
                      included={!plan.excludedToolIds.includes(tool.id)}
                      onToggle={() => onChange(withToolToggled(plan, tool.id))}
                    />
                  ))}
                </section>
              );
            })}
          </TooltipProvider>
        </div>
      )}

      <div className="flex max-w-[60ch] flex-col gap-1">
        <Text className="text-(--gray-10) text-[11.5px] leading-snug">
          {error ??
            "A tool mise installs needs a multi-step install, so picking one means the image is built in a builder session."}
        </Text>
        {error === null && (
          <Text className="text-(--gray-10) text-[11.5px] leading-snug">
            The image records what it carries, so sessions on it are told to
            reach for these instead of the slower defaults.
          </Text>
        )}
      </div>
    </StepBody>
  );
}

function ToolRow({
  tool,
  included,
  onToggle,
}: {
  tool: ImagePresetTool;
  included: boolean;
  onToggle: () => void;
}) {
  const checkboxId = useId();
  const dim = included ? "" : "opacity-60";
  return (
    <div className="grid grid-cols-[1rem_8rem_minmax(0,1fr)_3.5rem_2.5rem_1rem] items-center gap-x-3 border-(--gray-4) border-b px-3 py-1.5 transition-colors last:border-b-0 hover:bg-(--gray-2) motion-reduce:transition-none">
      <Checkbox
        id={checkboxId}
        checked={included}
        onCheckedChange={onToggle}
        aria-label={`Include ${tool.name}`}
        data-attr={`environment-setup-tool-${tool.id}`}
      />
      <label htmlFor={checkboxId} className={`cursor-pointer ${dim}`}>
        <code
          title={tool.name}
          className="font-mono text-(--gray-12) text-[12px]"
        >
          {tool.command}
        </code>
      </label>
      <div className={`min-w-0 ${dim}`}>
        <ToolReason htmlFor={checkboxId} reason={tool.reason} />
      </div>
      <span
        className={`text-right text-(--gray-10) text-[11px] tabular-nums ${dim}`}
      >
        {tool.sizeMb} MB
      </span>
      <span
        title={
          isDirectlyInstallable(tool)
            ? "Installed straight from the spec"
            : "Installed by a builder session"
        }
        className={`font-mono text-(--gray-10) text-[10.5px] ${dim}`}
      >
        {toolInstallMethod(tool)}
      </span>
      <a
        href={tool.url}
        target="_blank"
        rel="noreferrer"
        title={`Open the ${tool.name} docs`}
        className="inline-flex justify-end text-(--gray-8) hover:text-(--gray-12)"
      >
        <ArrowSquareOut size={12} aria-hidden="true" />
        <span className="sr-only">{`${tool.name} docs`}</span>
      </a>
    </div>
  );
}

/**
 * The reason, on one line so every row is the same height, with the whole
 * sentence on hover for the ones the line cuts.
 */
function ToolReason({ htmlFor, reason }: { htmlFor: string; reason: string }) {
  return (
    <Tooltip disableHoverablePopup>
      <TooltipTrigger
        render={
          <label
            htmlFor={htmlFor}
            className="block cursor-pointer truncate text-(--gray-11) text-[11.5px] leading-snug"
          >
            {reason}
          </label>
        }
      />
      <TooltipContent
        side="top"
        className="pointer-events-none max-w-[280px] select-none"
      >
        {reason}
      </TooltipContent>
    </Tooltip>
  );
}
