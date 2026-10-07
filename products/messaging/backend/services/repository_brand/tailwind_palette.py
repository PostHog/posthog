SHADES = ("50", "100", "200", "300", "400", "500", "600", "700", "800", "900", "950")

_V3_ROWS = {
    "slate": "#f8fafc #f1f5f9 #e2e8f0 #cbd5e1 #94a3b8 #64748b #475569 #334155 #1e293b #0f172a #020617",
    "gray": "#f9fafb #f3f4f6 #e5e7eb #d1d5db #9ca3af #6b7280 #4b5563 #374151 #1f2937 #111827 #030712",
    "zinc": "#fafafa #f4f4f5 #e4e4e7 #d4d4d8 #a1a1aa #71717a #52525b #3f3f46 #27272a #18181b #09090b",
    "neutral": "#fafafa #f5f5f5 #e5e5e5 #d4d4d4 #a3a3a3 #737373 #525252 #404040 #262626 #171717 #0a0a0a",
    "stone": "#fafaf9 #f5f5f4 #e7e5e4 #d6d3d1 #a8a29e #78716c #57534e #44403c #292524 #1c1917 #0c0a09",
    "red": "#fef2f2 #fee2e2 #fecaca #fca5a5 #f87171 #ef4444 #dc2626 #b91c1c #991b1b #7f1d1d #450a0a",
    "orange": "#fff7ed #ffedd5 #fed7aa #fdba74 #fb923c #f97316 #ea580c #c2410c #9a3412 #7c2d12 #431407",
    "amber": "#fffbeb #fef3c7 #fde68a #fcd34d #fbbf24 #f59e0b #d97706 #b45309 #92400e #78350f #451a03",
    "yellow": "#fefce8 #fef9c3 #fef08a #fde047 #facc15 #eab308 #ca8a04 #a16207 #854d0e #713f12 #422006",
    "lime": "#f7fee7 #ecfccb #d9f99d #bef264 #a3e635 #84cc16 #65a30d #4d7c0f #3f6212 #365314 #1a2e05",
    "green": "#f0fdf4 #dcfce7 #bbf7d0 #86efac #4ade80 #22c55e #16a34a #15803d #166534 #14532d #052e16",
    "emerald": "#ecfdf5 #d1fae5 #a7f3d0 #6ee7b7 #34d399 #10b981 #059669 #047857 #065f46 #064e3b #022c22",
    "teal": "#f0fdfa #ccfbf1 #99f6e4 #5eead4 #2dd4bf #14b8a6 #0d9488 #0f766e #115e59 #134e4a #042f2e",
    "cyan": "#ecfeff #cffafe #a5f3fc #67e8f9 #22d3ee #06b6d4 #0891b2 #0e7490 #155e75 #164e63 #083344",
    "sky": "#f0f9ff #e0f2fe #bae6fd #7dd3fc #38bdf8 #0ea5e9 #0284c7 #0369a1 #075985 #0c4a6e #082f49",
    "blue": "#eff6ff #dbeafe #bfdbfe #93c5fd #60a5fa #3b82f6 #2563eb #1d4ed8 #1e40af #1e3a8a #172554",
    "indigo": "#eef2ff #e0e7ff #c7d2fe #a5b4fc #818cf8 #6366f1 #4f46e5 #4338ca #3730a3 #312e81 #1e1b4b",
    "violet": "#f5f3ff #ede9fe #ddd6fe #c4b5fd #a78bfa #8b5cf6 #7c3aed #6d28d9 #5b21b6 #4c1d95 #2e1065",
    "purple": "#faf5ff #f3e8ff #e9d5ff #d8b4fe #c084fc #a855f7 #9333ea #7e22ce #6b21a8 #581c87 #3b0764",
    "fuchsia": "#fdf4ff #fae8ff #f5d0fe #f0abfc #e879f9 #d946ef #c026d3 #a21caf #86198f #701a75 #4a044e",
    "pink": "#fdf2f8 #fce7f3 #fbcfe8 #f9a8d4 #f472b6 #ec4899 #db2777 #be185d #9d174d #831843 #500724",
    "rose": "#fff1f2 #ffe4e6 #fecdd3 #fda4af #fb7185 #f43f5e #e11d48 #be123c #9f1239 #881337 #4c0519",
}

_V4_ROWS = {
    "slate": "#f8fafc #f1f5f9 #e2e8f0 #cad5e2 #90a1b9 #62748e #45556c #314158 #1d293d #0f172b #020618",
    "gray": "#f9fafb #f3f4f6 #e5e7eb #d1d5dc #99a1af #6a7282 #4a5565 #364153 #1e2939 #101828 #030712",
    "zinc": "#fafafa #f4f4f5 #e4e4e7 #d4d4d8 #9f9fa9 #71717b #52525c #3f3f46 #27272a #18181b #09090b",
    "neutral": "#fafafa #f5f5f5 #e5e5e5 #d4d4d4 #a1a1a1 #737373 #525252 #404040 #262626 #171717 #0a0a0a",
    "stone": "#fafaf9 #f5f5f4 #e7e5e4 #d6d3d1 #a6a09b #79716b #57534d #44403b #292524 #1c1917 #0c0a09",
    "red": "#fef2f2 #ffe2e2 #ffc9c9 #ffa2a2 #ff6467 #fb2c36 #e7000b #c10007 #9f0712 #82181a #460809",
    "orange": "#fff7ed #ffedd4 #ffd6a7 #ffb86a #ff8904 #ff6900 #f54900 #ca3500 #9f2d00 #7e2a0c #441306",
    "amber": "#fffbeb #fef3c6 #fee685 #ffd230 #ffb900 #fe9a00 #e17100 #bb4d00 #973c00 #7b3306 #461901",
    "yellow": "#fefce8 #fef9c2 #fff085 #ffdf20 #fdc700 #f0b100 #d08700 #a65f00 #894b00 #733e0a #432004",
    "lime": "#f7fee7 #ecfcca #d8f999 #bbf451 #9ae600 #7ccf00 #5ea500 #497d00 #3c6300 #35530e #192e03",
    "green": "#f0fdf4 #dcfce7 #b9f8cf #7bf1a8 #05df72 #00c950 #00a63e #008236 #016630 #0d542b #032e15",
    "emerald": "#ecfdf5 #d0fae5 #a4f4cf #5ee9b5 #00d492 #00bc7d #009966 #007a55 #006045 #004f3b #002c22",
    "teal": "#f0fdfa #cbfbf1 #96f7e4 #46ecd5 #00d5be #00bba7 #009689 #00786f #005f5a #0b4f4a #022f2e",
    "cyan": "#ecfeff #cefafe #a2f4fd #53eafd #00d3f2 #00b8db #0092b8 #007595 #005f78 #104e64 #053345",
    "sky": "#f0f9ff #dff2fe #b8e6fe #74d4ff #00bcff #00a6f4 #0084d1 #0069a8 #00598a #024a70 #052f4a",
    "blue": "#eff6ff #dbeafe #bedbff #8ec5ff #51a2ff #2b7fff #155dfc #1447e6 #193cb8 #1c398e #162456",
    "indigo": "#eef2ff #e0e7ff #c6d2ff #a3b3ff #7c86ff #615fff #4f39f6 #432dd7 #372aac #312c85 #1e1a4d",
    "violet": "#f5f3ff #ede9fe #ddd6ff #c4b4ff #a684ff #8e51ff #7f22fe #7008e7 #5d0ec0 #4d179a #2f0d68",
    "purple": "#faf5ff #f3e8ff #e9d4ff #dab2ff #c27aff #ad46ff #9810fa #8200db #6e11b0 #59168b #3c0366",
    "fuchsia": "#fdf4ff #fae8ff #f6cfff #f4a8ff #ed6aff #e12afb #c800de #a800b7 #8a0194 #721378 #4b004f",
    "pink": "#fdf2f8 #fce7f3 #fccee8 #fda5d5 #fb64b6 #f6339a #e60076 #c6005c #a3004c #861043 #510424",
    "rose": "#fff1f2 #ffe4e6 #ffccd3 #ffa1ad #ff637e #ff2056 #ec003f #c70036 #a50036 #8b0836 #4d0218",
}


def _palette(rows: dict[str, str]) -> dict[str, dict[str, str]]:
    return {name: dict(zip(SHADES, row.split(), strict=True)) for name, row in rows.items()}


TAILWIND_V3_PALETTE = _palette(_V3_ROWS)
TAILWIND_V4_PALETTE = _palette(_V4_ROWS)
