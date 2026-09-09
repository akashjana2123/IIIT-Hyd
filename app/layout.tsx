import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "SARAL | Grounded science communication",
  description: "Audience-adaptive, evidence-linked scripts and slide bullets.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}

