"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const CURRENT_SEASON = 2026;

const LINKS = [
  { href: "/", label: "Predictions" },
  { href: `/${CURRENT_SEASON}`, label: "Seasons" },
  { href: "/compare", label: "Compare" },
] as const;

/**
 * One nav, everywhere — home, season pages, event pages, the legacy compare
 * page. Previously each page carried its own "Formula Uno" wordmark plus a
 * one-off cross-link ("← Predictions", "Compare drivers →"), which meant
 * three different, slightly inconsistent ideas of how the app connects to
 * itself. This replaces all of that with a single persistent header.
 */
export default function NavBar() {
  const pathname = usePathname();
  const inSeasonArea = /^\/\d{4}(\/|$)/.test(pathname);

  function isActive(href: string): boolean {
    if (href === "/") return pathname === "/";
    if (href === "/compare") return pathname.startsWith("/compare");
    return inSeasonArea;
  }

  return (
    <nav className="sticky top-0 z-30 border-b border-black/10 dark:border-white/10 bg-background/85 backdrop-blur-sm">
      <div className="max-w-5xl mx-auto px-4 sm:px-6 h-12 flex items-center justify-between">
        <Link href="/" className="text-xs tracking-widest uppercase text-accent font-semibold">
          Formula Uno
        </Link>
        <div className="flex items-center gap-5">
          {LINKS.map((l) => (
            <Link
              key={l.href}
              href={l.href}
              className={`text-sm transition-colors ${
                isActive(l.href)
                  ? "text-foreground font-medium"
                  : "text-black/50 dark:text-white/50 hover:text-black dark:hover:text-white"
              }`}
            >
              {l.label}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  );
}
