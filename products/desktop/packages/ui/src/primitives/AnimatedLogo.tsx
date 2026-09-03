import { cn } from "@posthog/quill";

interface SpineGradient {
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  from: string;
  to: string;
  toOffset?: number;
}

interface SpinePiece {
  d: string;
  gradient: SpineGradient;
}

interface ColorSpine {
  name: string;
  pieces: SpinePiece[];
}

const COLOR_SPINES: ColorSpine[] = [
  {
    name: "blue",
    pieces: [
      {
        d: "M10.7401 7.14295L4.58711 0.815297C2.91642 -0.907781 0 0.279746 0 2.67808V7.50968L10.7401 18.733V7.14295Z",
        gradient: {
          x1: -5.32989,
          y1: 1.80181,
          x2: 10.5828,
          y2: 19.5159,
          from: "#3F80FF",
          to: "#084FE0",
        },
      },
      {
        d: "M10.74 18.725V28.0001H8.94141L0 18.1836V7.50946L10.74 18.725Z",
        gradient: {
          x1: -4.87954,
          y1: 13.8113,
          x2: 8.63346,
          y2: 27.9769,
          from: "#0255FF",
          to: "#0145D2",
        },
      },
      {
        d: "M0 25.4097C0 26.8403 1.15978 28.0001 2.59044 28.0001H8.94531L0 18.18V25.4097Z",
        gradient: {
          x1: -0.225829,
          y1: 18.94,
          x2: 8.99613,
          y2: 28.2656,
          from: "#0041C6",
          to: "#0045D0",
        },
      },
    ],
  },
  {
    name: "red",
    pieces: [
      {
        d: "M21.9693 7.64927L15.3273 0.815174C13.6567 -0.907902 10.7402 0.279623 10.7402 2.67796V7.14998L21.9693 18.6921V7.64927Z",
        gradient: {
          x1: 10.5502,
          y1: 7.25342,
          x2: 21.7409,
          y2: 18.6513,
          from: "#FF651E",
          to: "#E4400A",
        },
      },
      {
        d: "M10.7402 7.14294V18.733L19.6001 28.0003H21.9693V18.6922L10.7402 7.14294Z",
        gradient: {
          x1: 10.4326,
          y1: 7.36636,
          x2: 22.4422,
          y2: 28.233,
          from: "#EF3C00",
          to: "#D63601",
        },
      },
      {
        d: "M10.7402 28.0003H19.6001L10.7402 18.733V28.0003Z",
        gradient: {
          x1: 10.1324,
          y1: 19.6762,
          x2: 16.4046,
          y2: 27.9771,
          from: "#C42C00",
          to: "#D63600",
        },
      },
    ],
  },
  {
    name: "yellow",
    pieces: [
      {
        d: "M33.2915 19.2975V7.74241L26.5563 0.815175C24.8857 -0.907902 21.9692 0.279624 21.9692 2.67796V7.64998L33.2915 19.2917V19.2975Z",
        gradient: {
          x1: 21.692,
          y1: 1.96207,
          x2: 33.1011,
          y2: 18.7755,
          from: "#FFD849",
          to: "#FBAE01",
          toOffset: 0.955762,
        },
      },
      {
        d: "M21.9692 7.64935V18.6922L31.0154 28.0003H33.2915V19.29L21.9692 7.64935Z",
        gradient: {
          x1: 21.692,
          y1: 7.96689,
          x2: 33.1011,
          y2: 27.9328,
          from: "#FFB700",
          to: "#F9AA01",
        },
      },
      {
        d: "M21.9692 28.0003H31.0154L21.9692 18.6922V28.0003Z",
        gradient: {
          x1: 21.8448,
          y1: 18.9105,
          x2: 30.7559,
          y2: 27.977,
          from: "#FF9500",
          to: "#F8AA00",
        },
      },
    ],
  },
];

const MONO_SPINES: string[] = [
  "M0 19.4722C0 19.0154 0.562522 18.7976 0.870117 19.1352L8.18359 27.1636C8.47606 27.4846 8.24778 28.0005 7.81348 28.0005H2.59082C1.16027 28.0005 0.000175258 26.8411 0 25.4106V19.4722Z",
  "M0 8.75537C0.000102115 8.30476 0.549647 8.08418 0.861328 8.40966L18.8115 27.1548C19.1157 27.4727 18.8903 28.0004 18.4502 28.0005H11.3643C11.2206 28.0004 11.0841 27.9385 10.9893 27.8306L8.94141 25.5005L0.129883 15.8237C0.0461713 15.7317 0 15.6112 0 15.4868V8.75537Z",
  "M0 2.67822C0.000232954 0.280142 2.91627 -0.906899 4.58691 0.815913L30.1904 27.1519C30.4986 27.4688 30.2741 28.0005 29.832 28.0005H22.0674C21.9254 28.0005 21.7901 27.9401 21.6953 27.8345L19.5996 25.5005L0.277344 5.30029C0.0995493 5.11432 0.000123238 4.86713 0 4.60986V2.67822Z",
  "M10.7402 2.67822C10.7406 0.280393 13.6565 -0.90731 15.3271 0.814937L32.5049 18.481L33 18.9907V26.2866C33 26.7329 32.46 26.9556 32.1455 26.6392L31.0156 25.5005L11.3066 5.23291C10.9436 4.85957 10.7402 4.35913 10.7402 3.83837V2.67822Z",
  "M21.9697 2.67822C21.97 0.280137 24.886 -0.907072 26.5566 0.815913L33.0078 7.45752V15.269C33.0078 15.7179 32.4623 15.9394 32.1494 15.6177L22.5352 5.73291C22.1721 5.35957 21.9697 4.85911 21.9697 4.33837V2.67822Z",
];

const HEAD_COLOR =
  "M50.01 23.3376L49.6723 23.2968C48.6653 23.1687 47.7281 22.7031 47.0179 21.9696L33.2856 7.74255V28.0003H48.9971C50.4757 28.0003 51.669 26.8012 51.669 25.3284V25.2236C51.669 24.2631 50.953 23.454 50.0041 23.3376H50.01ZM39.2 23.5471C38.2162 23.5471 37.4187 22.7496 37.4187 21.7658C37.4187 20.7821 38.2162 19.9845 39.2 19.9845C40.1838 19.9845 40.9813 20.7821 40.9813 21.7658C40.9813 22.7496 40.1838 23.5471 39.2 23.5471Z";

const HEAD_MONO =
  "M34.7178 10.4585C34.7181 10.009 35.2659 9.78832 35.5781 10.1118L47.0234 21.9702C47.7336 22.7037 48.6716 23.1693 49.6787 23.2974L50.0156 23.3384H50.0098C50.9586 23.4548 51.6748 24.2636 51.6748 25.2241V25.3286C51.6748 26.8014 50.4815 28.0005 49.0029 28.0005H35.2207C34.9446 28.0005 34.7207 27.7766 34.7207 27.5005L34.7178 10.4585ZM39.2061 19.9849C38.2224 19.9849 37.425 20.7825 37.4248 21.7661C37.4248 22.7499 38.2223 23.5474 39.2061 23.5474C40.1898 23.5473 40.9873 22.7498 40.9873 21.7661C40.9872 20.7825 40.1897 19.9849 39.2061 19.9849Z";

const EYE = { cx: 39.2, cy: 21.76, r: 1.85 };

const MARK_WIDTH = 52;
const MARK_HEIGHT = 28;

const COLOR_SPINE_STAGGER_MS = 130;
const MONO_SPINE_STAGGER_MS = 80;

function gradientId(spine: ColorSpine, index: number): string {
  return `animated-logo-${spine.name}-${index + 1}`;
}

interface AnimatedLogoProps {
  size?: number;
  animate?: "always" | "hover";
  className?: string;
  "data-testid"?: string;
}

export function AnimatedLogo({
  size = 72,
  animate = "always",
  className,
  "data-testid": testId,
}: AnimatedLogoProps) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox={`0 0 ${MARK_WIDTH} ${MARK_HEIGHT}`}
      width={size}
      height={(size * MARK_HEIGHT) / MARK_WIDTH}
      aria-hidden="true"
      data-testid={testId}
      className={cn(
        "select-none overflow-visible",
        animate === "hover" ? "animated-logo-hover" : "pointer-events-none",
        className,
      )}
    >
      <defs>
        {COLOR_SPINES.flatMap((spine) =>
          spine.pieces.map((piece, index) => (
            <linearGradient
              key={gradientId(spine, index)}
              id={gradientId(spine, index)}
              gradientUnits="userSpaceOnUse"
              x1={piece.gradient.x1}
              y1={piece.gradient.y1}
              x2={piece.gradient.x2}
              y2={piece.gradient.y2}
            >
              <stop stopColor={piece.gradient.from} />
              <stop
                offset={piece.gradient.toOffset ?? 1}
                stopColor={piece.gradient.to}
              />
            </linearGradient>
          )),
        )}
      </defs>
      {COLOR_SPINES.map((spine, spineIndex) => (
        <g
          key={spine.name}
          className="animated-logo-spine dark:hidden"
          style={{
            animationDelay: `${spineIndex * COLOR_SPINE_STAGGER_MS}ms`,
          }}
        >
          {spine.pieces.map((piece, index) => (
            <path
              key={gradientId(spine, index)}
              d={piece.d}
              fill={`url(#${gradientId(spine, index)})`}
            />
          ))}
        </g>
      ))}
      {MONO_SPINES.map((d, index) => (
        <path
          key={d}
          className="animated-logo-spine hidden fill-[#FAFAFA] dark:block"
          style={{ animationDelay: `${index * MONO_SPINE_STAGGER_MS}ms` }}
          d={d}
        />
      ))}
      <path className="dark:hidden" d={HEAD_COLOR} fill="#111111" />
      <path className="hidden fill-[#FAFAFA] dark:block" d={HEAD_MONO} />
      <circle
        className="animated-logo-eyelid fill-[#111111] dark:fill-[#FAFAFA]"
        cx={EYE.cx}
        cy={EYE.cy}
        r={EYE.r}
      />
    </svg>
  );
}
