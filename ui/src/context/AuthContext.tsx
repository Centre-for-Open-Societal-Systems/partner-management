"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from "react";

interface AuthUser {
  sub?: string;
  email?: string;
  name?: string;
  preferred_username?: string;
  [k: string]: unknown;
}

interface AuthContextType {
  user: AuthUser | null;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [errorCode, setErrorCode] = useState<string | null>(null);

  const login = useCallback(() => {
    window.location.href = `/api/login?redirect_uri=${encodeURIComponent(
      window.location.href
    )}`;
  }, []);

  const logout = useCallback(() => {
    window.location.href = "/api/logout";
  }, []);

  useEffect(() => {
    async function init() {
      try {
        const res = await fetch("/api/me", { cache: "no-store" });
        if (res.status === 401) {
          // No session, or one IAM no longer accepts (expired, or a cookie left by
          // another portal): log in again. IAM reports this in its own envelope
          // (response_header.response_error_code), the BFF in `errors`; either
          // way a 401 means "log in". Guard against a loop: if a login just
          // came back and is still refused, show the error instead.
          const KEY = "pm-login-attempt";
          const last = Number(sessionStorage.getItem(KEY) || 0);
          if (Date.now() - last > 30_000) {
            sessionStorage.setItem(KEY, String(Date.now()));
            login();
            return;
          }
          sessionStorage.removeItem(KEY);
          setErrorCode("AUTH_GENERIC_ERROR");
          return;
        }
        if (res.status === 413) return setErrorCode("G2P-AUT-413");
        if (res.status === 403) return setErrorCode("G2P-AUT-403");

        const data = await res.json();
        if (res.ok) setUser(data);
      } catch (e) {
        console.error("Auth init failed", e);
        setErrorCode("AUTH_GENERIC_ERROR");
      } finally {
        setIsLoading(false);
      }
    }
    init();

    // API client dispatches this when a call returns 401.
    const onUnauthorized = () => login();
    window.addEventListener("auth:unauthorized", onUnauthorized);
    return () => window.removeEventListener("auth:unauthorized", onUnauthorized);
  }, [login]);

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <p className="text-[color:var(--color-text-muted)]">Loading…</p>
      </div>
    );
  }

  if (errorCode === "G2P-AUT-403") {
    return (
      <Centered
        title="Access denied"
        message="You do not have permission to use the Partner Management portal. Ask an administrator to grant you the 'partner_manager' role."
      />
    );
  }
  if (errorCode === "G2P-AUT-413") {
    return (
      <Centered
        title="Token too large"
        message="Your access token exceeds the allowed size limit due to too many assigned roles. Please contact your administrator."
      />
    );
  }
  if (errorCode) {
    return (
      <Centered
        title="Something went wrong"
        message="We could not verify your session. Please try again later."
      />
    );
  }
  if (!user) return null;

  return (
    <AuthContext.Provider value={{ user, logout }}>{children}</AuthContext.Provider>
  );
}

function Centered({ title, message }: { title: string; message: string }) {
  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <div className="card max-w-lg text-center">
        <h1 className="text-2xl mb-3">{title}</h1>
        <p className="text-[color:var(--color-text-muted)]">{message}</p>
      </div>
    </div>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
