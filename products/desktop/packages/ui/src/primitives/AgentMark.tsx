/**
 * The agent's mark: a ring with a filled centre.
 *
 * Two concentric circles and nothing else. It reads as a presence rather than as
 * a character, which is what the agent is on these surfaces, and it stays legible
 * at 11px beside body text.
 */
export function AgentMark({
  size = 12,
  className,
}: {
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <circle cx="8" cy="8" r="6.25" stroke="currentColor" strokeWidth="1.5" />
      <circle cx="8" cy="8" r="2.5" fill="currentColor" />
    </svg>
  );
}
