import type { Metadata } from "next";
import { GeistMono } from "geist/font/mono";
import "@fontsource/ibm-plex-sans/latin-500.css";
import "@fontsource/ibm-plex-sans/latin-600.css";
import "@fontsource/ibm-plex-sans/latin-700.css";
import { AppTheme } from "@/components/app-theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "Self-Healing App — Daytona × Scalingo",
  description: "Incident recovery with Daytona sandboxes and Scalingo deployments.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={GeistMono.variable} data-theme="dark" suppressHydrationWarning>
      <body><AppTheme>{children}</AppTheme></body>
    </html>
  );
}
