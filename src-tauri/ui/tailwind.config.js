/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx,js,jsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        bg: "#0e121c",
        panel: "#161c2a",
        elev: "#1d2436",
        line: "#2a3349",
        text: "#f5f5fa",
        dim: "#aac8ff",
        grey: "#8c96aa",
        cyan: { DEFAULT: "#5ec8ff", dim: "#3c82b4" },
        yellow: "#ffc857",
        red: "#ff6b6b",
        green: "#5eddb3",
      },
      fontFamily: {
        sans: ["-apple-system", "SF Pro Display", "Helvetica Neue", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SF Mono", "Menlo", "monospace"],
      },
      animation: {
        "gradient-x": "gradient-x 8s ease infinite",
        "border-spin": "border-spin 6s linear infinite",
        "pulse-slow": "pulse 4s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fade-in 0.4s ease forwards",
      },
      keyframes: {
        "gradient-x": {
          "0%, 100%": { "background-position": "0% 50%" },
          "50%": { "background-position": "100% 50%" },
        },
        "border-spin": {
          to: { transform: "rotate(360deg)" },
        },
        "fade-in": {
          from: { opacity: "0", transform: "translateY(4px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
      },
    },
  },
  plugins: [],
};