import type { Metadata } from "next";
import { UserProfile } from "@clerk/nextjs";
import { auth } from "@clerk/nextjs/server";
import { redirect } from "next/navigation";
import { AuthUnavailable } from "@/app/auth-unavailable";
import { isAuthConfigured } from "@/lib/auth-config";

export const metadata: Metadata = {
  title: "Профиль и безопасность",
};

export default async function ProfilePage() {
  if (!isAuthConfigured()) return <AuthUnavailable />;

  const { userId } = await auth();
  if (!userId) redirect("/sign-in?redirect_url=%2Faccount%2Fprofile");

  return (
    <section className="profile-page" aria-labelledby="profile-title">
      <div>
        <p className="eyebrow">Личный кабинет</p>
        <h1 id="profile-title">Профиль и безопасность</h1>
      </div>
      <div className="profile-widget">
        <UserProfile path="/account/profile" />
      </div>
    </section>
  );
}
