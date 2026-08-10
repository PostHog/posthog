import confetti from "canvas-confetti";

const POSTHOG_COLORS = ["#f54d00", "#f8be2a", "#1d4aff", "#000000", "#ffffff"];

function reducedMotion(): boolean {
  return (
    window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false
  );
}

export function celebrate(options?: confetti.Options): void {
  if (reducedMotion()) return;
  confetti({
    particleCount: 80,
    spread: 70,
    origin: { y: 0.7 },
    colors: POSTHOG_COLORS,
    ...options,
  });
}

export function shipIt(): void {
  if (reducedMotion()) return;
  const end = Date.now() + 1200;
  const fire = () => {
    confetti({
      particleCount: 6,
      angle: 60,
      spread: 55,
      origin: { x: 0, y: 0.8 },
      colors: POSTHOG_COLORS,
    });
    confetti({
      particleCount: 6,
      angle: 120,
      spread: 55,
      origin: { x: 1, y: 0.8 },
      colors: POSTHOG_COLORS,
    });
    if (Date.now() < end) requestAnimationFrame(fire);
  };
  fire();
}

export function fireFrom(
  element: HTMLElement,
  options?: confetti.Options,
): void {
  if (reducedMotion()) return;
  const rect = element.getBoundingClientRect();
  const x = (rect.left + rect.width / 2) / window.innerWidth;
  const y = (rect.top + rect.height / 2) / window.innerHeight;
  confetti({
    particleCount: 40,
    spread: 60,
    startVelocity: 35,
    origin: { x, y },
    colors: POSTHOG_COLORS,
    ...options,
  });
}
