// Mock kit definitions per hobby. Replace with real `/kit/build` response
// from the backend once teammate's endpoint ships — the shape is the same.

const SNOWBOARDING_KIT = {
  hobby: "snowboarding",
  default_budget_usd: 300,
  items: [
    {
      slot: "snowboard",
      label: "Snowboard",
      category: "essential",
      preferences: [
        { key: "type", value: "all-mountain", reason: "Best beginner profile — handles groomers and powder, forgiving on early turns." },
        { key: "flex", value: "soft-medium", reason: "Soft-medium flex is more forgiving while you're learning to control edges." },
      ],
      price_range_usd: [80, 160],
      default_checked: true,
    },
    {
      slot: "bindings",
      label: "Bindings",
      category: "essential",
      preferences: [
        { key: "size", value: "M/L", reason: "Sized to fit a size 10 boot." },
        { key: "compat", value: "fits boot 10", reason: "Cross-checked against the boot size you mentioned." },
      ],
      price_range_usd: [30, 80],
      default_checked: true,
    },
    {
      slot: "boots",
      label: "Snowboard boots",
      category: "essential",
      preferences: [
        { key: "size", value: "size 10", reason: "From the size you mentioned in your brief." },
        { key: "flex", value: "soft-medium", reason: "Comfort-first for a beginner who'll be on them all day." },
      ],
      price_range_usd: [40, 90],
      default_checked: true,
    },
    {
      slot: "helmet",
      label: "Helmet",
      category: "essential",
      preferences: [
        { key: "feature", value: "MIPS preferred", reason: "MIPS adds rotational impact protection — recommended for new riders." },
      ],
      price_range_usd: [20, 50],
      default_checked: false,
    },
    {
      slot: "goggles",
      label: "Goggles",
      category: "nice_to_have",
      preferences: [
        { key: "lens", value: "all-condition lens", reason: "One lens that handles bright and overcast days simplifies a starter kit." },
      ],
      price_range_usd: [15, 40],
      default_checked: true,
    },
    {
      slot: "jacket",
      label: "Outerwear jacket",
      category: "nice_to_have",
      preferences: [
        { key: "feature", value: "waterproof", reason: "10k+ waterproof rating keeps you dry on resort snow." },
      ],
      price_range_usd: [25, 70],
      default_checked: true,
    },
    {
      slot: "pants",
      label: "Snow pants",
      category: "nice_to_have",
      preferences: [],
      price_range_usd: [20, 60],
      default_checked: true,
    },
  ],
};

const PHOTOGRAPHY_KIT = {
  hobby: "photography",
  default_budget_usd: 400,
  items: [
    {
      slot: "camera_body",
      label: "Camera body",
      category: "essential",
      preferences: [
        { key: "type", value: "entry DSLR", reason: "Entry DSLRs (Canon Rebel, Nikon D3xxx) are the cheapest path into manual control." },
        { key: "shutter", value: "<20k actuations", reason: "Shutter count under 20k means most of the body's life is still ahead." },
      ],
      price_range_usd: [180, 320],
      default_checked: true,
    },
    {
      slot: "lens",
      label: "Lens",
      category: "essential",
      preferences: [
        { key: "type", value: "50mm prime", reason: "A nifty-fifty teaches composition before zoom habits set in." },
        { key: "aperture", value: "f/1.8 or wider", reason: "Wider apertures mean better low-light shots without a tripod." },
      ],
      price_range_usd: [40, 120],
      default_checked: true,
    },
    {
      slot: "memory_card",
      label: "Memory card",
      category: "essential",
      preferences: [
        { key: "size", value: "32GB+", reason: "Enough headroom for a full day of RAW photos without offloading." },
      ],
      price_range_usd: [10, 25],
      default_checked: true,
    },
    {
      slot: "tripod",
      label: "Tripod",
      category: "nice_to_have",
      preferences: [
        { key: "type", value: "travel-size", reason: "Travel tripods fit a backpack — likelier you'll actually carry it." },
      ],
      price_range_usd: [25, 80],
      default_checked: true,
    },
    {
      slot: "bag",
      label: "Camera bag",
      category: "nice_to_have",
      preferences: [],
      price_range_usd: [20, 60],
      default_checked: true,
    },
  ],
};

const POTTERY_KIT = {
  hobby: "pottery",
  default_budget_usd: 200,
  items: [
    {
      slot: "wheel",
      label: "Pottery wheel",
      category: "essential",
      preferences: [
        { key: "type", value: "tabletop", reason: "Tabletop wheels are the cheapest second-hand entry point — splurge later." },
        { key: "motor", value: "1/3 hp+", reason: "Anything weaker bogs down on larger pieces." },
      ],
      price_range_usd: [80, 180],
      default_checked: true,
    },
    {
      slot: "clay",
      label: "Starter clay",
      category: "essential",
      preferences: [
        { key: "weight", value: "25 lb", reason: "Enough for ~10 small pieces while you're learning." },
        { key: "type", value: "low-fire", reason: "Low-fire is forgiving and most community kilns can fire it." },
      ],
      price_range_usd: [15, 35],
      default_checked: true,
    },
    {
      slot: "tools",
      label: "Hand tools set",
      category: "essential",
      preferences: [
        { key: "type", value: "starter set", reason: "A 10–12 piece set covers everything you'll touch in your first month." },
      ],
      price_range_usd: [10, 25],
      default_checked: true,
    },
    {
      slot: "apron",
      label: "Apron + towel",
      category: "nice_to_have",
      preferences: [],
      price_range_usd: [10, 25],
      default_checked: false,
    },
  ],
};

const GUITAR_KIT = {
  hobby: "guitar",
  default_budget_usd: 250,
  items: [
    {
      slot: "guitar",
      label: "Acoustic guitar",
      category: "essential",
      preferences: [
        { key: "type", value: "dreadnought", reason: "Dreadnought is the most forgiving body shape for new players." },
        { key: "size", value: "full-size", reason: "Estimated from your build; smaller bodies feel cramped past month one." },
      ],
      price_range_usd: [120, 220],
      default_checked: true,
    },
    {
      slot: "tuner",
      label: "Tuner",
      category: "essential",
      preferences: [
        { key: "type", value: "clip-on", reason: "Clip-on tuners ignore room noise and beat any phone app for accuracy." },
      ],
      price_range_usd: [8, 20],
      default_checked: true,
    },
    {
      slot: "strap",
      label: "Strap",
      category: "nice_to_have",
      preferences: [],
      price_range_usd: [8, 25],
      default_checked: true,
    },
  ],
};

const GENERIC_KIT = {
  hobby: "this hobby",
  default_budget_usd: 250,
  items: [
    {
      slot: "primary",
      label: "Primary gear",
      category: "essential",
      preferences: [
        { key: "type", value: "beginner-friendly", reason: "Skewed toward forgiving entry-level gear that teaches good habits." },
      ],
      price_range_usd: [100, 200],
      default_checked: true,
    },
    {
      slot: "tools",
      label: "Supporting tools",
      category: "essential",
      preferences: [],
      price_range_usd: [20, 60],
      default_checked: true,
    },
    {
      slot: "bag",
      label: "Storage / bag",
      category: "nice_to_have",
      preferences: [],
      price_range_usd: [15, 40],
      default_checked: true,
    },
  ],
};

const TEMPLATES = {
  snowboarding: SNOWBOARDING_KIT,
  photography: PHOTOGRAPHY_KIT,
  pottery: POTTERY_KIT,
  guitar: GUITAR_KIT,
};

// Map vague keywords → canonical hobby key
const HOBBY_ALIASES = {
  snowboard: "snowboarding",
  snowboarding: "snowboarding",
  ski: "snowboarding", // close enough for kit composition
  skiing: "snowboarding",
  photo: "photography",
  photography: "photography",
  camera: "photography",
  pottery: "pottery",
  ceramics: "pottery",
  guitar: "guitar",
  acoustic: "guitar",
};

export function canonicalHobby(text) {
  if (!text) return null;
  const lower = String(text).toLowerCase();
  for (const [alias, canonical] of Object.entries(HOBBY_ALIASES)) {
    if (lower.includes(alias)) return canonical;
  }
  return null;
}

export function buildKitFor({ hobby, budgetUsd } = {}) {
  const canonical = hobby ? canonicalHobby(hobby) : null;
  const template = TEMPLATES[canonical] || GENERIC_KIT;
  return {
    kit_id: `mock-${canonical || "generic"}-${Date.now()}`,
    hobby: template.hobby,
    budget_usd: budgetUsd ?? template.default_budget_usd,
    items: template.items.map((it) => ({
      ...it,
      preferences: it.preferences.map((p) => ({ ...p })),
      checked: it.default_checked,
    })),
  };
}

// ─── follow-up questions (Step 2) ──────────────────────────────────────────
// Backend's gen_followup() returns plain strings; the screen accepts richer
// {question, rationale, placeholder} objects. Until the backend enriches,
// we hand-author rationales per hobby for the demo case.

const FOLLOWUP_BY_HOBBY = {
  snowboarding: [
    {
      question: "How would you describe your experience?",
      rationale:
        "You said ‘beginner’ — give me a sentence so I can match flex and shape.",
      placeholder: "e.g. Never been, but I've skied for years…",
    },
    {
      question: "Where are you mostly riding?",
      rationale:
        "Different mountains call for different gear — PNW vs. dry Utah vs. icy East.",
      placeholder: "e.g. Mostly Park City and Brighton…",
    },
    {
      question: "How many days do you plan to ride this season?",
      rationale: "Helps me decide how durable the gear needs to be.",
      placeholder: "e.g. Maybe 8 weekend days…",
    },
    {
      question: "What matters most when I negotiate?",
      rationale: "I'll weight tradeoffs against this when comparing listings.",
      placeholder: "e.g. Best quality I can get without going over $300…",
    },
  ],
  photography: [
    {
      question: "What kind of subjects are you shooting?",
      rationale: "Portraits, landscapes, and street need different lenses.",
      placeholder: "e.g. Mostly travel and street photography…",
    },
    {
      question: "Are you comfortable with manual settings?",
      rationale:
        "Tells me whether to skew toward simpler bodies or more capable manual controls.",
      placeholder: "e.g. I've shot on auto for years and want to learn manual…",
    },
    {
      question: "What matters most when I negotiate?",
      rationale: "I'll weight tradeoffs against this when comparing listings.",
      placeholder: "e.g. Lowest shutter count I can find under budget…",
    },
  ],
  pottery: [
    {
      question: "Will you have access to a kiln?",
      rationale:
        "Determines whether to prioritize air-dry clay or kiln-fired starter sets.",
      placeholder: "e.g. There's a community kiln at the rec center…",
    },
    {
      question: "How much space do you have to work with?",
      rationale: "Tabletop wheels vs. floor wheels are very different buys.",
      placeholder: "e.g. A small corner of my apartment…",
    },
  ],
};

const FOLLOWUP_GENERIC = [
  {
    question: "Tell me a bit more about your experience.",
    rationale: "Helps me skew toward beginner-friendly or pro-level gear.",
    placeholder: "e.g. Total beginner, never tried…",
  },
  {
    question: "Where will you mostly use this gear?",
    rationale: "Environment affects what features matter.",
    placeholder: "e.g. Mostly at home, sometimes travel…",
  },
  {
    question: "What matters most when I negotiate?",
    rationale: "I'll weight tradeoffs against this when comparing listings.",
    placeholder: "e.g. Best quality I can get within budget…",
  },
];

export function followupFor(hobby) {
  const canonical = canonicalHobby(hobby);
  return FOLLOWUP_BY_HOBBY[canonical] || FOLLOWUP_GENERIC;
}

// ─── candidates (Picker) and active-search (Step 4) — unchanged ────────────

export const MOCK_CANDIDATES = {
  snowboard: [
    {
      listing_id: "fb-1",
      title: "Burton Custom 158",
      price_usd: 120,
      list_price_usd: 140,
      image_url: null,
      condition: "good",
      rating: 4.5,
      location: "Salt Lake City · 4mi · Marcus T.",
      blurb:
        "All-mountain shape, beginner-friendly flex. Cosmetic top-sheet scrape, edges sharp.",
      is_top_match: true,
    },
    {
      listing_id: "fb-2",
      title: "Burton Ripcord 154",
      price_usd: 95,
      list_price_usd: 130,
      image_url: null,
      condition: "good",
      rating: 4.2,
      location: "Provo · 22mi · Sandy K.",
      blurb: "Soft flex made for learning. Great reviews, almost too cheap.",
      is_top_match: false,
    },
    {
      listing_id: "fb-3",
      title: "Rossignol Sawblade 152",
      price_usd: 140,
      list_price_usd: 180,
      image_url: null,
      condition: "like_new",
      rating: 4.6,
      location: "Park City · 18mi · Sara L.",
      blurb: "Park-leaning, more aggressive than beginner needs.",
      is_top_match: false,
    },
    {
      listing_id: "fb-4",
      title: "K2 Standard 156",
      price_usd: 80,
      list_price_usd: 110,
      image_url: null,
      condition: "good",
      rating: 4.0,
      location: "Murray · 12mi · Aaron P.",
      blurb: "Cheapest option, base scuffed but rideable.",
      is_top_match: false,
    },
    {
      listing_id: "fb-5",
      title: "GNU Riders Choice 159",
      price_usd: 160,
      list_price_usd: 220,
      image_url: null,
      condition: "good",
      rating: 4.4,
      location: "Provo · 22mi · Priya S.",
      blurb: "Top reviews, fair tread of board, budget-tight.",
      is_top_match: false,
    },
  ],
};

export const MOCK_ACTIVE = {
  committed_usd: 250,
  budget_usd: 300,
  negotiating_count: 2,
  avg_counter_saving_pct: 14,
  agreed_count: 1,
  pickups_scheduled: 1,
  time_saved_hours: 6,
  listings_reviewed: 87,
  items: [
    { slot: "snowboard", label: "Snowboard", title: "Burton Custom 158", meta: "Good · Salt Lake · 4mi · Marcus T.", target_price: 100, list_price: 120, saving: 20, status: "negotiating", status_text: "Countered $100 · awaiting reply", added_label: "2d ago" },
    { slot: "bindings", label: "Bindings", title: "Burton Cartel · M/L", meta: "Like new · Sandy · Priya S.", target_price: 40, list_price: 45, saving: 5, status: "messaging", status_text: "Asked if compatible w/ Burton baseplate", added_label: "2d ago" },
    { slot: "boots", label: "Boots", title: "DC Phase Boa · 10", meta: "Fair · Ogden · 22mi · Jake R.", target_price: 50, list_price: 60, saving: 10, status: "just_found", status_text: "Just found · queued to message", added_label: "2d ago" },
    { slot: "goggles", label: "Goggles", title: "Anon Helix", meta: "Good · Provo · 18mi · Rin H.", target_price: 25, list_price: 30, saving: 5, status: "agreed", status_text: "Agreed $25 · pickup Saturday 2pm", added_label: "2d ago" },
  ],
  activity: [
    { time_label: "just now", text: "Marcus T. countered $115 on Burton Custom. Re-offered $108." },
    { time_label: "2 min ago", text: "Asked Priya S. if Cartel bindings fit a Burton baseplate." },
    { time_label: "5 min ago", text: "Agreed $25 with Rin H. on Anon Helix goggles." },
    { time_label: "12 min ago", text: "Found 3 new boot listings — added 1 to shortlist." },
    { time_label: "24 min ago", text: "Sent intro to Jake R. about size 10 boots." },
    { time_label: "1 hr ago", text: 'Started search · "snowboarding kit · $300".' },
  ],
};
