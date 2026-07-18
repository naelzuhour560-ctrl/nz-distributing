"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const links = [
  { href: "/", label: "Overview" },
  { href: "/stores", label: "Stores" },
  { href: "/products", label: "Products" },
  { href: "/routes", label: "Routes" },
];

export default function NavLinks() {
  const pathname = usePathname();

  return (
    <nav className="flex flex-col gap-1">
      {links.map(({ href, label }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            className={`block rounded px-3 py-2 text-sm font-medium ${
              active
                ? "bg-zinc-200 text-zinc-900 dark:bg-zinc-800 dark:text-zinc-100"
                : "text-zinc-600 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:bg-zinc-800"
            }`}
          >
            {label}
          </Link>
        );
      })}
    </nav>
  );
}
