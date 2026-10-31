import type { NextConfig } from "next";

const backend = process.env.CAMPAIGN_API_URL ?? "http://127.0.0.1:8000";
const agent = process.env.CAMPAIGN_AGENT_URL ?? "http://127.0.0.1:8001";

const config: NextConfig = {
  devIndicators: false,
  experimental: { proxyTimeout: 600_000 }, // картинки ждут своей очереди в генераторе
  output: "standalone",
  compress: false, // иначе статусы агента приходят одним куском
  async rewrites() {
    return [
      { source: "/api/backend/:path*", destination: `${backend}/:path*` },
      { source: "/api/agent/:path*", destination: `${agent}/:path*` },
    ];
  },
};

export default config;
