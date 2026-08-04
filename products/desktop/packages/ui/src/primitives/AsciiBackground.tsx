import {
  AsciiShader,
  type AsciiShaderColors,
} from "@posthog/ui/primitives/asciiShader";
import { resolveCssColorVar } from "@posthog/ui/primitives/cssColor";
import { DotPatternBackground } from "@posthog/ui/primitives/DotPatternBackground";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { useEffect, useRef, useState } from "react";

/** Neutral glyphs, with the theme accent reserved for the densest ones. */
const INK_VAR = "--gray-8";
const ACCENT_VAR = "--accent-9";
const INK_FALLBACK = [0.5, 0.5, 0.5] as const;
const ACCENT_FALLBACK = [0.95, 0.45, 0.15] as const;

interface AsciiBackgroundProps {
  className?: string;
  style?: React.CSSProperties;
}

function readColors(element: Element): AsciiShaderColors {
  return {
    ink: resolveCssColorVar(element, INK_VAR, INK_FALLBACK),
    accent: resolveCssColorVar(element, ACCENT_VAR, ACCENT_FALLBACK),
  };
}

/**
 * Ambient ASCII field for composer and hero screens. Drop-in replacement for
 * {@link DotPatternBackground}, which it falls back to wherever WebGL isn't
 * available (tests, a lost GPU context).
 */
export function AsciiBackground({ className, style }: AsciiBackgroundProps) {
  const isDarkMode = useThemeStore((state) => state.isDarkMode);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const shaderRef = useRef<AsciiShader | null>(null);
  const [shaderFailed, setShaderFailed] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || shaderFailed) {
      return;
    }

    const shader = AsciiShader.create(canvas, {
      ...readColors(canvas),
      animate: !window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    });
    if (!shader) {
      setShaderFailed(true);
      return;
    }
    shaderRef.current = shader;

    const onContextLost = (event: Event) => {
      event.preventDefault();
      setShaderFailed(true);
    };
    canvas.addEventListener("webglcontextlost", onContextLost);

    const resizeObserver = new ResizeObserver(() => {
      const { width, height } = canvas.getBoundingClientRect();
      shader.resize(width, height);
    });
    resizeObserver.observe(canvas);

    // Idle whenever the field can't be seen — a hidden window, or a surface
    // scrolled out of view.
    let onScreen = true;
    const syncRunning = () => {
      if (onScreen && !document.hidden) {
        shader.start();
      } else {
        shader.stop();
      }
    };
    const visibilityObserver = new IntersectionObserver((entries) => {
      onScreen = entries.some((entry) => entry.isIntersecting);
      syncRunning();
    });
    visibilityObserver.observe(canvas);
    document.addEventListener("visibilitychange", syncRunning);

    const { width, height } = canvas.getBoundingClientRect();
    shader.resize(width, height);
    shader.start();

    return () => {
      canvas.removeEventListener("webglcontextlost", onContextLost);
      document.removeEventListener("visibilitychange", syncRunning);
      resizeObserver.disconnect();
      visibilityObserver.disconnect();
      shader.dispose();
      shaderRef.current = null;
    };
  }, [shaderFailed]);

  // The shader holds resolved RGB rather than `var(...)`, so it has to re-read
  // the tokens whenever the appearance flips. The Radix `<Theme>` above us
  // swaps their values in the same commit as this flag.
  // biome-ignore lint/correctness/useExhaustiveDependencies: isDarkMode is the signal that the token values changed, not a value this effect reads
  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas && shaderRef.current) {
      shaderRef.current.setColors(readColors(canvas));
    }
  }, [isDarkMode]);

  if (shaderFailed) {
    return <DotPatternBackground className={className} style={style} />;
  }

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      tabIndex={-1}
      style={{
        maskImage: "linear-gradient(to top, black 0%, transparent 100%)",
        WebkitMaskImage: "linear-gradient(to top, black 0%, transparent 100%)",
        ...style,
      }}
      className={`pointer-events-none absolute bottom-0 left-0 h-full w-full opacity-60 ${className ?? ""}`}
    />
  );
}
