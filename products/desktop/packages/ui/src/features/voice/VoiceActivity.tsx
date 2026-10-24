import type { VoiceAudioLevels } from "@posthog/platform/speech";
import { motion, useReducedMotion } from "framer-motion";

export function VoiceActivity({
  levels,
}: {
  levels: VoiceAudioLevels;
}): React.JSX.Element {
  const reducedMotion = useReducedMotion();
  const input = Math.min(1, Math.sqrt(levels.input) * 2);
  const output = Math.min(1, Math.sqrt(levels.output) * 2);
  const energy = Math.max(input, output);
  return (
    <svg
      className="size-5 shrink-0"
      viewBox="0 -65 322 340"
      fill="none"
      aria-hidden="true"
    >
      <motion.g
        animate={{ y: reducedMotion ? 0 : -(input * 45 + output * 20) }}
        transition={{ duration: 0.18 }}
      >
        <path
          d="M0 72.4709V244.437C0 249.774 1.62921 254.718 4.38202 258.875C6.23596 261.628 8.59551 263.988 11.3483 265.842C12.6966 266.797 14.2135 267.583 15.7303 268.201C18.8202 269.493 22.191 270.224 25.7865 270.224H103.596V180.786L0 72.4709Z"
          fill="#0B54E8"
        />
        <path
          d="M103.652 68.9329L44.2697 7.86549C28.1461 -8.76372 0 2.69695 0 25.843V72.4722L103.652 180.787V68.9329Z"
          fill="#3271EC"
        />
      </motion.g>
      <motion.g
        animate={{ y: reducedMotion ? 0 : -energy * 60 }}
        transition={{ duration: 0.18 }}
      >
        <path
          d="M212.022 73.8201L147.921 7.865C131.797 -8.76421 103.651 2.69646 103.651 25.8425V68.8762L212.022 180.393V73.8201Z"
          fill="#F77133"
        />
        <path
          d="M103.651 270.224H189.157L103.651 180.786V270.224Z"
          fill="#C64F2D"
        />
        <path
          d="M103.651 68.9325V180.786L189.157 270.225H212.022V180.393L103.651 68.9325Z"
          fill="#CD562E"
        />
      </motion.g>
      <motion.g
        animate={{ y: reducedMotion ? 0 : -(input * 20 + output * 45) }}
        transition={{ duration: 0.18 }}
      >
        <path
          d="M212.022 73.8197V180.393L299.326 270.224H321.292V186.235L212.022 73.8197Z"
          fill="#F9AE2D"
        />
        <path
          d="M321.292 186.236V74.7189L256.292 7.865C240.169 -8.76421 212.022 2.69646 212.022 25.8425V73.7639L321.292 186.18V186.236Z"
          fill="#FACA55"
        />
        <path
          d="M212.022 270.225H299.326L212.022 180.394V270.225Z"
          fill="#F0A82D"
        />
      </motion.g>
    </svg>
  );
}
