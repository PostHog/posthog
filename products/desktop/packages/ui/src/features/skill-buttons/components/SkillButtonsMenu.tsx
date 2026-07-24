import { CaretDown } from "@phosphor-icons/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { track } from "../../../shell/analytics";
import { sendPromptToAgent } from "../../sessions/sendPromptToAgent";
import {
  buildSkillButtonPromptBlocks,
  SKILL_BUTTON_ORDER,
  SKILL_BUTTONS,
  type SkillButton,
  type SkillButtonId,
} from "../prompts";
import { useSkillButtonsStore } from "../skillButtonsStore";

interface SkillButtonsMenuProps {
  taskId: string;
}

function SkillButtonIcon({ button }: { button: SkillButton }) {
  const { Icon, color } = button;
  return <Icon size={14} weight="bold" color={color} />;
}

export function SkillButtonsMenu({ taskId }: SkillButtonsMenuProps) {
  const lastSelectedId = useSkillButtonsStore((s) => s.lastSelectedId);
  const setLastSelectedId = useSkillButtonsStore((s) => s.setLastSelectedId);

  const primaryButton = SKILL_BUTTONS[lastSelectedId];
  const dropdownButtons = SKILL_BUTTON_ORDER.filter(
    (id) => id !== lastSelectedId,
  ).map((id) => SKILL_BUTTONS[id]);

  const handleTrigger = (
    buttonId: SkillButtonId,
    source: "primary" | "dropdown",
  ) => {
    track(ANALYTICS_EVENTS.SKILL_BUTTON_TRIGGERED, {
      task_id: taskId,
      button_id: buttonId,
      source,
    });
    setLastSelectedId(buttonId);
    sendPromptToAgent(taskId, buildSkillButtonPromptBlocks(buttonId));
  };

  return (
    <TooltipProvider delay={500}>
      <div className="flex items-center">
        <Tooltip>
          <TooltipTrigger
            render={
              <Button
                variant="outline"
                size="sm"
                className="rounded-s-[3px] rounded-e-none"
                onClick={() => handleTrigger(primaryButton.id, "primary")}
              >
                <SkillButtonIcon button={primaryButton} />
                {primaryButton.label}
              </Button>
            }
          />
          <TooltipContent side="top">{primaryButton.tooltip}</TooltipContent>
        </Tooltip>
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button
                variant="outline"
                size="icon-sm"
                className="rounded-s-none rounded-e-[3px] border-s-0"
                aria-label="More skills"
              >
                <CaretDown size={14} weight="bold" />
              </Button>
            }
          />
          <DropdownMenuContent align="end" sideOffset={4} className="min-w-40">
            {dropdownButtons.map((button) => (
              <Tooltip key={button.id}>
                <TooltipTrigger
                  render={
                    <DropdownMenuItem
                      onClick={() => handleTrigger(button.id, "dropdown")}
                    >
                      <SkillButtonIcon button={button} />
                      {button.label}
                    </DropdownMenuItem>
                  }
                />
                <TooltipContent side="top">{button.tooltip}</TooltipContent>
              </Tooltip>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </TooltipProvider>
  );
}
