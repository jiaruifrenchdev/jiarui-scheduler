"use client";

import Image from "next/image";
import Link from "next/link";
import { useState } from "react";

import { BrandHeader } from "../brand-header";
import { EyeIcon, EyeOffIcon } from "../eye-icons";

type FieldErrors = Partial<
  Record<"email" | "fullName" | "phone" | "wechat" | "password" | "confirm", string>
>;

const WECHAT_ID_REGEX = /^[A-Za-z][A-Za-z0-9_-]{5,19}$/;
const EMAIL_REGEX = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/;

function hasChineseCharacters(value: string) {
  return /[\u3400-\u4DBF\u4E00-\u9FFF]/.test(value);
}

function isValidWeChatId(value: string) {
  return WECHAT_ID_REGEX.test(value);
}

function isValidEmail(value: string) {
  return EMAIL_REGEX.test(value);
}

export default function RegisterPage() {
  const [form, setForm] = useState({
    email: "",
    fullName: "",
    phone: "",
    wechat: "",
    password: "",
    confirm: "",
  });
  const [errors, setErrors] = useState<FieldErrors>({});
  const [zh, setZh] = useState(false);
  const [generalError, setGeneralError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [done, setDone] = useState(false);
  const [needsVerify, setNeedsVerify] = useState(false);

  const update =
    (key: keyof typeof form) =>
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const nextValue = e.target.value;
      setForm((f) => ({ ...f, [key]: nextValue }));

      if (key === "wechat") {
        const trimmed = nextValue.trim();
        setErrors((prev) => ({
          ...prev,
          wechat: trimmed
            ? hasChineseCharacters(trimmed) || !isValidWeChatId(trimmed)
              ? "WeChat ID must be 6-20 characters, use letters, numbers, underscores or hyphens, and start with a letter."
              : undefined
            : undefined,
        }));
      }

      if (key === "email") {
        const trimmed = nextValue.trim();
        setErrors((prev) => ({
          ...prev,
          email: trimmed
            ? !isValidEmail(trimmed)
              ? "Please enter a valid email address."
              : undefined
            : undefined,
        }));
      }
    };

  function validate(): FieldErrors {
    const e: FieldErrors = {};
    const emailValue = form.email.trim();
    if (!emailValue) e.email = "Email is required.";
    else if (!isValidEmail(emailValue)) e.email = "Please enter a valid email address.";
    if (!form.fullName.trim()) e.fullName = "Legal full name is required.";
    if (!form.phone.trim()) e.phone = "Phone number is required.";
    const wechatValue = form.wechat.trim();
    if (!wechatValue) e.wechat = "WeChat ID is required.";
    else if (hasChineseCharacters(wechatValue) || !isValidWeChatId(wechatValue))
      e.wechat = "WeChat ID must be 6-20 characters, use letters, numbers, underscores or hyphens, and start with a letter.";
    if (form.password.length < 8)
      e.password = "Password must be at least 8 characters.";
    if (form.confirm !== form.password)
      e.confirm = "Passwords do not match.";
    return e;
  }

  async function onSubmit(ev: React.FormEvent) {
    ev.preventDefault();
    setGeneralError(null);
    const v = validate();
    if (Object.keys(v).length) {
      setErrors(v);
      return;
    }
    setErrors({});
    setLoading(true);

    try {
      const response = await fetch(
        `${process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000"}/auth/register`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            email: form.email.trim(),
            password: form.password,
            full_name: form.fullName.trim(),
            phone: form.phone.trim(),
            wechat: form.wechat.trim(),
          }),
        },
      );

      const body = await response.json().catch(() => null);
      if (response.status === 409 && body?.detail) {
        const c = body.detail;
        setErrors({
          email: c.email_taken ? "This email is already registered." : undefined,
          phone: c.phone_taken ? "This phone number is already in use." : undefined,
          wechat: c.wechat_taken ? "This WeChat ID is already in use." : undefined,
        });
        return;
      }

      if (!response.ok) {
        setGeneralError(
          typeof body?.detail === "string"
            ? body.detail
            : "Could not create your account. Please try again.",
        );
        return;
      }

      setNeedsVerify(Boolean(body?.needs_verification));
      setDone(true);
    } catch {
      setGeneralError(
        "Could not reach the registration server. Please try again in a moment.",
      );
    } finally {
      setLoading(false);
    }
  }

  if (done) {
    return (
      <main className="auth-wrap">
        <div className="card">
          <BrandHeader />
          <h1 className="card-title">
            {needsVerify ? "Confirm your email" : "Account created"}
          </h1>
          <p className="card-sub">
            {needsVerify ? (
              <>
                We sent a confirmation link to <strong>{form.email}</strong>.
                Click it to activate your account, then log in. Check your spam
                folder if you don&apos;t see it within a few minutes.
              </>
            ) : (
              <>
                Your account for <strong>{form.email}</strong> is ready. You can
                log in now.
              </>
            )}
          </p>
          <Link href="/login" className="btn btn-primary">
            Go to login
          </Link>
        </div>
      </main>
    );
  }

  return (
    <main className="auth-wrap">
      <form className="card card-wide" onSubmit={onSubmit} noValidate>
        <BrandHeader />
        <h1 className="card-title">Create your account</h1>
        <p className="card-sub">Register to reserve exam-prep office hours.</p>

        <div className="owl-note" role="note">
          <Image
            src="/logo.png"
            alt=""
            width={44}
            height={44}
            className="owl-note-avatar"
            aria-hidden="true"
          />
          <div className="owl-note-bubble">
            <button
              type="button"
              className="owl-lang-toggle"
              onClick={() => setZh((v) => !v)}
              aria-label={zh ? "Switch to English" : "切换到中文"}
            >
              {zh ? "EN" : "中文"}
            </button>
            {zh ? (
              <>
                <p className="owl-note-head">咕咕！飞走之前，听我一句——</p>
                <ul className="owl-note-list">
                  <li>
                    <strong>姓名、邮箱、微信号</strong> 是我们核对预约的关键信息。
                  </li>
                  <li>
                    请 <strong>仔细填写并确认无误</strong>，注册后不易更改。
                  </li>
                </ul>
              </>
            ) : (
              <>
                <p className="owl-note-head">Hoot! Before you fly off —</p>
                <ul className="owl-note-list">
                  <li>
                    Your <strong>name, email, and WeChat ID</strong> are how we
                    match you to your reservation.
                  </li>
                  <li>
                    <strong>Double-check them</strong> — they can&apos;t be
                    easily changed later.
                  </li>
                </ul>
              </>
            )}
          </div>
        </div>

        {generalError && <div className="alert alert-error">{generalError}</div>}

        <div className="field-grid">
          <Field
            label="Legal full name"
            labelZh="姓名"
            value={form.fullName}
            onChange={update("fullName")}
            error={errors.fullName}
            placeholder="As on your ID"
            autoComplete="name"
          />
          <Field
            label="Email"
            labelZh="邮箱"
            type="email"
            value={form.email}
            onChange={update("email")}
            error={errors.email}
            placeholder="you@example.com"
            autoComplete="email"
          />
          <Field
            label="Phone number"
            labelZh="电话号码"
            value={form.phone}
            onChange={update("phone")}
            error={errors.phone}
            placeholder="+1 416 555 0123"
            autoComplete="tel"
          />
          <Field
            label="WeChat ID"
            labelZh="微信号"
            value={form.wechat}
            onChange={update("wechat")}
            error={errors.wechat}
            placeholder="your_wechat_id"
            autoComplete="username"
          />
          <Field
            label="Password"
            labelZh="密码"
            type="password"
            value={form.password}
            onChange={update("password")}
            error={errors.password}
            placeholder="At least 8 characters"
            autoComplete="new-password"
          />
          <Field
            label="Confirm password"
            labelZh="确认密码"
            type="password"
            value={form.confirm}
            onChange={update("confirm")}
            error={errors.confirm}
            placeholder="Re-enter your password"
            autoComplete="new-password"
          />
        </div>

        <button className="btn btn-primary" type="submit" disabled={loading}>
          {loading ? "Creating account…" : "Create account"}
        </button>

        <p className="foot-note">
          Already have an account? <Link href="/login" className="link">Log in</Link>
        </p>
      </form>
    </main>
  );
}

function Field({
  label,
  labelZh,
  error,
  type,
  ...props
}: {
  label: string;
  labelZh?: string;
  error?: string;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  const [reveal, setReveal] = useState(false);
  const isPassword = type === "password";
  const inputType = isPassword && reveal ? "text" : type;

  return (
    <div className="field">
      <label className="label">
        {label}
        {labelZh && <span className="label-zh"> / {labelZh}</span>}
      </label>
      <div className={isPassword ? "input-reveal" : undefined}>
        <input
          className="input"
          type={inputType}
          aria-invalid={error ? "true" : undefined}
          {...props}
        />
        {isPassword && (
          <button
            type="button"
            className="reveal-btn"
            onClick={() => setReveal((r) => !r)}
            aria-label={reveal ? "Hide password" : "Show password"}
            aria-pressed={reveal}
          >
            {reveal ? <EyeOffIcon /> : <EyeIcon />}
          </button>
        )}
      </div>
      {error && <span className="field-error">{error}</span>}
    </div>
  );
}
