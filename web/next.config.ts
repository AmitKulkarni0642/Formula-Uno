import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // Disabled: every page in this app is client-fetched from a live, constantly
  // changing backend (no static/ISR content exists), so Cache Components'
  // prerendering validation (Suspense-around-every-dynamic-hook) is pure
  // friction here with no caching benefit to show for it.
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
