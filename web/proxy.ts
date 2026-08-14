import { clerkMiddleware } from "@clerk/nextjs/server";
import { NextResponse, type NextFetchEvent, type NextRequest } from "next/server";

const configured = Boolean(
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY?.trim() &&
    process.env.CLERK_SECRET_KEY?.trim(),
);
const clerkProxy = configured ? clerkMiddleware() : null;

/**
 * Clerk получает сессию через Proxy в Next.js 16. Пока ключи не добавлены,
 * запросы проходят как раньше и публичный сайт продолжает работать.
 * Защита личных данных дополнительно выполняется в самих Server Components.
 */
export default function proxy(request: NextRequest, event: NextFetchEvent) {
  if (!clerkProxy) return NextResponse.next();
  return clerkProxy(request, event);
}

export const config = {
  matcher: [
    "/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)",
    "/(api|trpc)(.*)",
    "/__clerk/(.*)",
  ],
};
