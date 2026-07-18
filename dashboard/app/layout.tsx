import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import NavLinks from "./nav-links";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "N&Z Distributing",
  description: "Sales dashboard for N&Z Distributing",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex h-full">
        <aside className="flex w-56 shrink-0 flex-col border-r border-zinc-200 bg-zinc-50 p-4 dark:border-zinc-800 dark:bg-zinc-950">
          <h1 className="mb-6 text-lg font-bold tracking-tight">
            N&amp;Z Distributing
          </h1>
          <NavLinks />
        </aside>
        <main className="flex-1 overflow-y-auto p-8">{children}</main>
      </body>
    </html>
  );
}
