/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Channel-only OKLCH values defined in src/index.css :root.
        // Tailwind's <alpha-value> placeholder wires bg-accent/10, ring-accent/70, etc.
        canvas:    "oklch(var(--canvas) / <alpha-value>)",
        "canvas-2": "oklch(var(--canvas-2) / <alpha-value>)",
        "canvas-3": "oklch(var(--canvas-3) / <alpha-value>)",
        ink:       "oklch(var(--ink) / <alpha-value>)",
        edge:      "oklch(var(--edge) / <alpha-value>)",
        muted:     "oklch(var(--muted) / <alpha-value>)",
        accent:    "oklch(var(--accent) / <alpha-value>)",
        "accent-ink": "oklch(var(--accent-ink) / <alpha-value>)",
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "sans-serif"],
        mono: ["'IBM Plex Mono'", "ui-monospace", "SFMono-Regular", "monospace"],
        display: ["Chillax", "ui-sans-serif", "sans-serif"],
      },
      boxShadow: {
        "card": "var(--shadow-sm)",
        "card-lg": "var(--shadow-lg)",
        "glow": "0 0 0 4px var(--glow)",
      },
      transitionTimingFunction: {
        "out":    "var(--ease-out)",
        "in-out": "var(--ease-in-out)",
      },
    },
  },
  plugins: [],
};
