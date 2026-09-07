import { SKILL_BUTTONS, type SkillButtonId } from "../prompts";

interface SkillButtonActionMessageProps {
  buttonId: SkillButtonId;
}

export function SkillButtonActionMessage({
  buttonId,
}: SkillButtonActionMessageProps) {
  const { Icon, color, actionTitle, actionDescription } =
    SKILL_BUTTONS[buttonId];

  return (
    <div
      className="flex items-center gap-2 border-l-2 py-1 pl-3"
      style={{ borderColor: color }}
    >
      <Icon size={16} weight="bold" color={color} className="shrink-0" />
      <p className="text-sm leading-relaxed">
        <span className="font-medium" style={{ color }}>
          {actionTitle}
        </span>
        <span className="text-gray-11"> — {actionDescription}</span>
      </p>
    </div>
  );
}
