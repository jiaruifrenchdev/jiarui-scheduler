/**
 * Email-link landing page. Supabase sends verification (signup) and password
 * recovery links here. Handles both Supabase email-link styles:
 *   - token_hash + type  (recommended templates) -> verifyOtp
 *   - code               (default PKCE flow)      -> exchangeCodeForSession
 *
 * IMPORTANT: this runs the verification CLIENT-SIDE on purpose. The OTP token is
 * single-use, and email security scanners / link-tracking redirects routinely
 * pre-fetch links in transactional emails. A server route would consume the
 * token on that automated GET, so the real click then fails with "link already
 * used". Scanners don't execute JavaScript, so verifying in the browser lets the
 * token survive until an actual person opens the link.
 *
 * On a recovery link we send the user to /reset-password; otherwise to `next`.
 */
"use client";

import { type EmailOtpType } from "@supabase/supabase-js";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef } from "react";

import { createClient } from "@/lib/supabase/client";

function ConfirmInner() {
  const router = useRouter();
  const params = useSearchParams();
  // Guard against React 18 StrictMode double-invoking the effect in dev, which
  // would verify (consume) the token twice and fail the second time.
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;

    const token_hash = params.get("token_hash");
    const type = params.get("type") as EmailOtpType | null;
    const code = params.get("code");
    const next = params.get("next") ?? "/";

    async function run() {
      const supabase = createClient();
      let ok = false;

      if (token_hash && type) {
        const { error } = await supabase.auth.verifyOtp({ type, token_hash });
        ok = !error;
      } else if (code) {
        const { error } = await supabase.auth.exchangeCodeForSession(code);
        ok = !error;
      }

      if (ok) {
        const dest = type === "recovery" ? "/reset-password" : next;
        router.replace(dest);
      } else {
        router.replace("/auth/auth-code-error");
      }
    }

    run();
  }, [params, router]);

  return (
    <main className="auth-wrap">
      <div className="card">
        <div className="tricolore" style={{ marginBottom: "1.25rem", borderRadius: 2 }} />
        <h1 className="card-title">Confirming…</h1>
        <p className="card-sub" style={{ margin: 0 }}>
          Please wait while we verify your link.
        </p>
      </div>
    </main>
  );
}

export default function ConfirmPage() {
  // useSearchParams requires a Suspense boundary in the App Router.
  return (
    <Suspense fallback={null}>
      <ConfirmInner />
    </Suspense>
  );
}
