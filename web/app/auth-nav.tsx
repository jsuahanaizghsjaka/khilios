"use client";

import { Show, UserButton } from "@clerk/nextjs";
import Link from "next/link";

export function AuthNav() {
  return (
    <>
      <Show when="signed-out">
        <Link href="/sign-in">Войти</Link>
        <Link href="/sign-up" className="nav-account">
          Регистрация
        </Link>
      </Show>
      <Show when="signed-in">
        <Link href="/account" className="nav-account">
          Кабинет
        </Link>
        <UserButton
          userProfileUrl="/account/profile"
          appearance={{ elements: { avatarBox: "account-avatar" } }}
        />
      </Show>
    </>
  );
}
