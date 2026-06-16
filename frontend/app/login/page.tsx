"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { createClient } from "@/lib/supabase/client";
import { REMEMBER_COOKIE, REMEMBER_MAX_AGE } from "@/lib/supabase/constants";
import { BrandHeader } from "../brand-header";
import { EyeIcon, EyeOffIcon } from "../eye-icons";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [remember, setRemember] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [needsVerify, setNeedsVerify] = useState(false);
  const [loading, setLoading] = useState(false);

  async function onSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    setError(null);
    setNeedsVerify(false);
    setLoading(true);

    // Record the choice so the middleware refreshes cookies with a matching
    // lifetime ("Remember me", PROJECT_SPEC §3).
    document.cookie = `${REMEMBER_COOKIE}=${remember ? "1" : "0"};path=/;samesite=lax${
      remember ? `;max-age=${REMEMBER_MAX_AGE}` : ""
    }`;

    const supabase = createClient(remember);
    const { error } = await supabase.auth.signInWithPassword({ email, password });
    setLoading(false);

    if (error) {
      if (/email not confirmed/i.test(error.message)) {
        setNeedsVerify(true);
      } else {
        setError("Invalid email or password.");
      }
      return;
    }

    router.push("/");
    router.refresh();
  }

  return (
    <main className="auth-wrap">
      <form className="card" onSubmit={onSubmit} noValidate>
        <BrandHeader />
        <h1 className="card-title">Welcome back</h1>
        <p className="card-sub">Log in to manage your office-hour reservations.</p>

        {needsVerify && (
          <div className="alert alert-error">
            Please verify your email first — check your inbox for the link we sent
            when you registered.
          </div>
        )}
        {error && <div className="alert alert-error">{error}</div>}

        <div className="field">
          <label className="label">Email</label>
          <input
            className="input"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
            autoComplete="email"
            required
          />
        </div>

        <div className="field">
          <label className="label">Password</label>
          <div className="input-reveal">
            <input
              className="input"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Your password"
              autoComplete="current-password"
              required
            />
            <button
              type="button"
              className="reveal-btn"
              onClick={() => setShowPassword((s) => !s)}
              aria-label={showPassword ? "Hide password" : "Show password"}
              aria-pressed={showPassword}
            >
              {showPassword ? <EyeOffIcon /> : <EyeIcon />}
            </button>
          </div>
        </div>

        <div className="row-between">
          <label className="checkbox-row">
            <input
              type="checkbox"
              checked={remember}
              onChange={(e) => setRemember(e.target.checked)}
            />
            Remember me
          </label>
          <Link href="/forgot-password" className="link">
            Forgot password?
          </Link>
        </div>

        <button className="btn btn-primary" type="submit" disabled={loading}>
          {loading ? "Logging in…" : "Log in"}
        </button>

        <p className="foot-note">
          No account yet? <Link href="/register" className="link">Create one</Link>
        </p>
      </form>
    </main>
  );
}
