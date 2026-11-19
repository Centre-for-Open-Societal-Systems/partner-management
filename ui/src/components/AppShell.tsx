"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import Image from "next/image";
import { useAuth } from "@/context/AuthContext";

// Onboarding is a button on Partners; /onboard keeps Partners highlighted.
const NAV = [
  { href: "/partners", label: "Partners", also: ["/onboard"] },
  { href: "/requests", label: "Approvals", also: [] as string[] },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const who =
    (user?.preferred_username as string) ||
    (user?.email as string) ||
    (user?.name as string) ||
    "Staff";

  return (
    <div className="flex min-h-screen">
      <aside className="w-[280px] shrink-0 bg-[color:var(--color-brand-black)] text-white flex flex-col">
        <div className="px-6 py-6 border-b border-white/10">
          <Image
            src="/openg2p-logo-dark.svg"
            alt="OpenG2P"
            width={167}
            height={38}
            priority
            className="h-auto w-[167px]"
          />
          <div className="mt-5 text-xl font-medium text-white font-[family-name:var(--font-roboto-slab)]">
            Partner Management
          </div>
        </div>
        <nav className="flex-1 py-4">
          {NAV.map((item) => {
            const active = [item.href, ...item.also].some(
              (h) => pathname === h || pathname.startsWith(h + "/")
            );
            return (
              <Link
                key={item.href}
                href={item.href}
                className={
                  "block px-5 py-2.5 text-sm border-l-[3px] " +
                  (active
                    ? "border-[color:var(--color-brand-yellow)] bg-white/5 text-white font-semibold"
                    : "border-transparent text-white/70 hover:text-white hover:bg-white/5")
                }
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="px-5 py-4 border-t border-white/10 text-sm">
          <div className="text-white/60 mb-2 truncate" title={who}>
            {who}
          </div>
          <button
            onClick={logout}
            className="text-white/80 hover:text-white underline underline-offset-2"
          >
            Log out
          </button>
        </div>
      </aside>

      <main className="flex-1 overflow-x-auto">
        <div className="max-w-[1200px] mx-auto px-8 py-8">{children}</div>
      </main>
    </div>
  );
}
