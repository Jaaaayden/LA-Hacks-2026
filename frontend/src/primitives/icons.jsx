// Inline SVG icon set. Keep simple, monochrome, currentColor-driven.

const base = { width: 16, height: 16, viewBox: "0 0 16 16", fill: "none" };

export const ArrowLeftIcon = (p) => (
  <svg {...base} {...p}>
    <path
      d="M10 3L5 8l5 5"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const ArrowRightIcon = (p) => (
  <svg {...base} {...p}>
    <path
      d="M6 3l5 5-5 5"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const InfoIcon = (p) => (
  <svg {...base} {...p}>
    <circle cx="8" cy="8" r="6.25" stroke="currentColor" strokeWidth="1.2" />
    <path
      d="M8 7v4"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
    />
    <circle cx="8" cy="5" r="0.8" fill="currentColor" />
  </svg>
);

export const XIcon = (p) => (
  <svg {...base} {...p}>
    <path
      d="M4 4l8 8M12 4l-8 8"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
    />
  </svg>
);

export const PlusIcon = (p) => (
  <svg {...base} {...p}>
    <path
      d="M8 3v10M3 8h10"
      stroke="currentColor"
      strokeWidth="1.4"
      strokeLinecap="round"
    />
  </svg>
);

export const CheckIcon = (p) => (
  <svg {...base} {...p}>
    <path
      d="M3.5 8.5l3 3 6-6"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

export const StarIcon = (p) => (
  <svg {...base} {...p}>
    <path
      d="M8 1.6l1.95 3.95 4.36.63-3.16 3.08.75 4.34L8 11.55l-3.9 2.05.75-4.34L1.7 6.18l4.36-.63z"
      fill="currentColor"
    />
  </svg>
);

export const DotIcon = (p) => (
  <svg {...base} {...p}>
    <circle cx="8" cy="8" r="3" fill="currentColor" />
  </svg>
);

// Category placeholder glyphs (used when image_url is missing/garbage)
export const SnowboardGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <rect
      x="17"
      y="5"
      width="6"
      height="30"
      rx="3"
      fill="#3a4ad6"
      opacity="0.85"
    />
    <rect x="17" y="14" width="6" height="2" fill="#fff" opacity="0.7" />
    <rect x="17" y="22" width="6" height="2" fill="#fff" opacity="0.7" />
  </svg>
);

export const BindingsGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <rect x="10" y="14" width="20" height="12" rx="3" fill="#2a2a2a" />
    <rect x="13" y="17" width="14" height="2" rx="1" fill="#999" />
    <rect x="13" y="21" width="14" height="2" rx="1" fill="#999" />
  </svg>
);

export const BootsGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <path
      d="M14 8h7v18a4 4 0 01-4 4h-3a4 4 0 01-4-4v-3l4-1V8z"
      fill="#3a3026"
    />
    <rect x="14" y="22" width="11" height="4" fill="#5a4a3a" opacity="0.6" />
  </svg>
);

export const GogglesGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <rect x="6" y="14" width="28" height="12" rx="6" fill="#d97706" />
    <rect x="9" y="17" width="22" height="6" rx="3" fill="#fff" opacity="0.5" />
  </svg>
);

export const HelmetGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <path d="M8 22a12 12 0 0124 0v6H8v-6z" fill="#444" />
    <rect x="12" y="22" width="16" height="3" fill="#222" opacity="0.5" />
  </svg>
);

export const JacketGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <path
      d="M12 8l8-3 8 3v22a2 2 0 01-2 2H14a2 2 0 01-2-2V8z"
      fill="#2c5530"
    />
    <path d="M20 5v27" stroke="#fff" strokeWidth="0.8" opacity="0.6" />
  </svg>
);

export const PantsGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <path
      d="M14 6h12l1 26h-5l-1.5-16H19l-1.5 16h-5L14 6z"
      fill="#3a3a3a"
    />
  </svg>
);

export const GenericGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <rect
      x="9"
      y="9"
      width="22"
      height="22"
      rx="3"
      stroke="#9a958a"
      strokeWidth="1.5"
      fill="#e9e4d8"
    />
    <path
      d="M14 16h12M14 20h12M14 24h8"
      stroke="#9a958a"
      strokeWidth="1.4"
      strokeLinecap="round"
    />
  </svg>
);

export const CameraGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <rect x="6" y="13" width="28" height="18" rx="3" fill="#2a2a2a" />
    <circle cx="20" cy="22" r="5" fill="#5a5a5a" />
    <circle cx="20" cy="22" r="2" fill="#0f0f0f" />
    <rect x="14" y="10" width="6" height="3" fill="#444" />
  </svg>
);

export const LensGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <circle cx="20" cy="20" r="11" fill="#2a2a2a" />
    <circle cx="20" cy="20" r="7" fill="#1a1a1a" />
    <circle cx="20" cy="20" r="3" fill="#3a3a3a" />
  </svg>
);

export const TripodGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <rect x="16" y="6" width="8" height="8" fill="#3a3a3a" />
    <path
      d="M20 14l-8 18M20 14l8 18M20 14v18"
      stroke="#3a3a3a"
      strokeWidth="2"
      strokeLinecap="round"
    />
  </svg>
);

export const ClayGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <circle cx="20" cy="28" r="11" fill="#a86b3a" />
    <ellipse cx="20" cy="13" rx="10" ry="3" fill="#7a4a25" />
    <path d="M10 13v15" stroke="#7a4a25" strokeWidth="0.8" />
    <path d="M30 13v15" stroke="#7a4a25" strokeWidth="0.8" />
  </svg>
);

export const WheelGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <circle cx="20" cy="20" r="13" fill="#5a5a5a" />
    <circle cx="20" cy="20" r="9" fill="#3a3a3a" />
    <circle cx="20" cy="20" r="2" fill="#a8a8a8" />
  </svg>
);

export const GuitarGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <circle cx="22" cy="26" r="10" fill="#b07842" />
    <circle cx="22" cy="26" r="3" fill="#0f0f0f" />
    <rect x="19" y="6" width="6" height="18" fill="#7a5230" />
    <rect x="20" y="4" width="4" height="3" fill="#3a2818" />
  </svg>
);

export const AmpGlyph = (p) => (
  <svg width="40" height="40" viewBox="0 0 40 40" fill="none" {...p}>
    <rect x="6" y="10" width="28" height="22" rx="2" fill="#2a2a2a" />
    <circle cx="14" cy="21" r="5" fill="#1a1a1a" />
    <circle cx="14" cy="21" r="2.5" fill="#5a5a5a" />
    <rect x="22" y="14" width="10" height="3" fill="#5a5a5a" />
    <rect x="22" y="20" width="10" height="3" fill="#5a5a5a" />
  </svg>
);

const SLOT_GLYPHS = {
  // snowboarding
  snowboard: SnowboardGlyph,
  bindings: BindingsGlyph,
  boots: BootsGlyph,
  goggles: GogglesGlyph,
  helmet: HelmetGlyph,
  jacket: JacketGlyph,
  pants: PantsGlyph,
  // photography
  camera_body: CameraGlyph,
  lens: LensGlyph,
  tripod: TripodGlyph,
  bag: GenericGlyph,
  memory_card: GenericGlyph,
  // pottery
  clay: ClayGlyph,
  wheel: WheelGlyph,
  tools: GenericGlyph,
  apron: JacketGlyph,
  // guitar
  guitar: GuitarGlyph,
  amp: AmpGlyph,
  tuner: GenericGlyph,
  strap: GenericGlyph,
};

export function getSlotGlyph(slot) {
  return SLOT_GLYPHS[slot] || GenericGlyph;
}
