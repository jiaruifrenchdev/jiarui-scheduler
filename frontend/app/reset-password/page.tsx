"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { createClient } from "@/lib/supabase/client";
import { EyeIcon, EyeOffIcon } from "../eye-icons";

export default function ResetPasswordPage() {
  const router = useRouter();
  const [checking, setChecking] = useState(true);
  const [hasSession, setHasSession] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);

  useEffect(() => {
    // The recovery link (via /auth/confirm) established a session. Confirm it.
    const supabase = createClient();
    supabase.auth.getUser().then(({ data }) => {
      setHasSession(Boolean(data.user));
      setChecking(false);
    });
  }, []);

  async function onSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    setError(null);
    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords do not match.");
      return;
    }
    setLoading(true);

    const supabase = createClient();
    const { error } = await supabase.auth.updateUser({ password });
    setLoading(false);

    if (error) {
      setError(error.message);
      return;
    }
    setDone(true);
    setTimeout(() => router.push("/login"), 1600);
  }

  if (checking) {
    return (
      <main className="auth-wrap">
        <div className="card">
          <p className="card-sub" style={{ margin: 0 }}>Verifying your reset link…</p>
        </div>
      </main>
    );
  }

  if (!hasSession) {
    return (
      <main className="auth-wrap">
        <div className="card">
          <div className="tricolore" style={{ marginBottom: "1.25rem", borderRadius: 2 }} />
          <h1 className="card-title">Link expired</h1>
          <p className="card-sub">
            This password reset link is invalid or has expired. Request a new one.
          </p>
          <Link href="/forgot-password" className="btn btn-primary">
            Request a new link
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="auth-wrap">
      <form className="card" onSubmit={onSubmit} noValidate>
        <div className="tricolore" style={{ marginBottom: "1.25rem", borderRadius: 2 }} />
        <h1 className="card-title">Set a new password</h1>
        <p className="card-sub">Choose a strong password you don&apos;t use elsewhere.</p>

        {done && (
          <div className="alert alert-success">
            Password updated. Redirecting you to login…
          </div>
        )}
        {error && <div className="alert alert-error">{error}</div>}

        <div className="field">
          <label className="label">New password</label>
          <div className="input-reveal">
            <input
              className="input"
              type={showPassword ? "text" : "password"}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="At least 8 characters"
              autoComplete="new-password"
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
        <div className="field">
          <label className="label">Confirm new password</label>
          <div className="input-reveal">
            <input
              className="input"
              type={showPassword ? "text" : "password"}
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              placeholder="Re-enter your new password"
              autoComplete="new-password"
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

        <button className="btn btn-primary" type="submit" disabled={loading || done}>
          {loading ? "Updating…" : "Update password"}
        </button>
      </form>
    </main>
  );
}
