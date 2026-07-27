import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "CareerCraft",
  description:
    "Parse a resume, rank job postings against it with explained scores, and draft grounded cover letters — entirely on your machine.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-dvh antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-md focus:bg-primary focus:px-4 focus:py-2 focus:text-primary-foreground"
        >
          Skip to content
        </a>
        {children}
      </body>
    </html>
  );
}
