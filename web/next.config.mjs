/** @type {import('next').NextConfig} */
const nextConfig = {
  // standalone bundles only the files the server actually needs, which is what
  // keeps the runtime Docker stage from carrying all of node_modules.
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
};

export default nextConfig;
