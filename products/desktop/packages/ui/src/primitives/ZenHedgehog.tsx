import { motion } from "framer-motion";
import { useRef, useState } from "react";
import roboZen from "../assets/images/robo-zen.png";
import zenHedgehog from "../assets/images/zen.png";

const DELAY_MS = 400; // calm pause before shaking starts
const GROW_MS = 3500; // time to reach full intensity
const MAX_X = 15; // px
const MAX_ROTATE = 7; // deg
const MIN_FREQ = 8; // Hz at onset
const MAX_FREQ = 26; // Hz at peak

export function ZenHedgehog() {
  const [hovered, setHovered] = useState(false);
  const imgRef = useRef<HTMLImageElement>(null);
  const rafRef = useRef<number | null>(null);
  const enterTimeRef = useRef<number | null>(null);

  const tick = (now: number) => {
    if (!enterTimeRef.current) enterTimeRef.current = now;
    const elapsed = now - enterTimeRef.current;
    const t = Math.max(0, elapsed - DELAY_MS);
    const progress = Math.min(t / GROW_MS, 1);
    const amplitude = progress * progress; // quadratic ease-in

    if (amplitude > 0 && imgRef.current) {
      const freq = MIN_FREQ + (MAX_FREQ - MIN_FREQ) * progress;
      const phase = (now / 1000) * freq * 2 * Math.PI;
      const x = Math.sin(phase) * MAX_X * amplitude;
      const rotate = Math.sin(phase + 0.5) * MAX_ROTATE * amplitude;
      const scale = 1 + Math.sin(phase * 1.7) * 0.03 * amplitude;
      imgRef.current.style.transform = `translateX(${x}px) rotate(${rotate}deg) scale(${scale})`;
    }

    rafRef.current = requestAnimationFrame(tick);
  };

  const handleMouseEnter = () => {
    setHovered(true);
    enterTimeRef.current = null;
    rafRef.current = requestAnimationFrame(tick);
  };

  const handleMouseLeave = () => {
    setHovered(false);
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    enterTimeRef.current = null;
    if (imgRef.current) {
      imgRef.current.style.transform = "";
    }
  };

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: decorative hover animation
    <div
      className="zen-float"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      <motion.img
        ref={imgRef}
        layoutId="zen-hedgehog"
        src={hovered ? roboZen : zenHedgehog}
        alt=""
        transition={{ type: "spring", stiffness: 120, damping: 20, mass: 0.8 }}
        className="block w-[600px] max-w-[90%] cursor-default"
      />
    </div>
  );
}
