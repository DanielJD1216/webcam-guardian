/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx,js,jsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#f7f8fb",
        panel: "#ffffff",
        elev: "#f0f2f7",
        line: "#dde2eb",
        text: "#0c1320",
        dim: "#2667d4",
        grey: "#6b7589",
        cyan: { DEFAULT: "#0b80d1", dim: "#7fbbe7" },
        yellow: "#c47a00",
        red: "#c43a3a",
        green: "#1f8f5f",
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