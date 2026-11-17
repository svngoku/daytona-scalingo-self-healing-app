import type { NextConfig } from "next";
import path from "node:path";

const apiOrigin = (process.env.ORCHESTRATOR_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");

const config: NextConfig = {
  poweredByHeader: false,
  devIndicators: false,
  turbopack: { root: path.resolve(__dirname, "../..") },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiOrigin}/api/:path*` }];
  },
};

export default config;
