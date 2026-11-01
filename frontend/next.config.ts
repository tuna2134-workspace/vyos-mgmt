import type { NextConfig } from "next";

/**
 * The whole frontend is a client-rendered static export. The backend serves
 * `frontend/out` at `/` and exposes the API at `/api/v1`. Never add server
 * actions, route handlers, middleware, next/image optimization or routes with
 * dynamic path params here.
 */
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  reactStrictMode: true,
  // Silence Next's monorepo-root detection warning: the parent directory has
  // its own pnpm lockfile that does not belong to this app.
  outputFileTracingRoot: process.cwd(),
};

export default nextConfig;
