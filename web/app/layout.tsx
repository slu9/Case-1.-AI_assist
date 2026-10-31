import type { Metadata } from "next";
import { Onest, Unbounded } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/Providers";
import { TopBar } from "@/components/TopBar";

const font = Onest({ subsets: ["latin", "cyrillic"], variable: "--font-sans" });
const display = Unbounded({ subsets: ["latin", "cyrillic"], variable: "--font-display" });

export const metadata: Metadata = {
  title: "Campaign Assistant",
  description: "Рекламные кампании через диалог с AI",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" className={`${font.variable} ${display.variable}`}>
      <body>
        <Providers>
          <TopBar />
          <main className="main">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
