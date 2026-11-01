"use client";

import * as React from "react";
import { useQueryClient } from "@tanstack/react-query";

import {
  SESSION_EXPIRED_EVENT,
  api,
  clearAccessToken,
  refreshSession,
  setAccessToken,
} from "@/lib/api";
import type { LoginRequest, TokenResponse, User } from "@/lib/types";

export type AuthStatus = "loading" | "authenticated" | "unauthenticated";

interface AuthContextValue {
  user: User | null;
  status: AuthStatus;
  isAuthenticated: boolean;
  sessionExpired: boolean;
  login: (credentials: LoginRequest) => Promise<User>;
  logout: () => Promise<void>;
  refresh: () => Promise<User | null>;
  forceSignOut: () => void;
  clearSessionExpired: () => void;
}

const AuthContext = React.createContext<AuthContextValue | null>(null);

/**
 * Non-sensitive hint that a refresh cookie probably exists. The refresh cookie
 * itself is HttpOnly, so without this we would have to call /auth/refresh on a
 * first visit to /login/ just to learn that there is no session (and browsers
 * would log a noisy 401). The hint contains no token or user data.
 */
const SESSION_HINT_COOKIE = "vyos_mgmt_session_hint";
const SESSION_HINT_MAX_AGE = 7 * 24 * 60 * 60;

function secureCookieSuffix(): string {
  return typeof window !== "undefined" && window.location.protocol === "https:"
    ? "; Secure"
    : "";
}

function hasSessionHint(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie
    .split(";")
    .some((entry) => entry.trim() === `${SESSION_HINT_COOKIE}=1`);
}

function setSessionHint(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${SESSION_HINT_COOKIE}=1; Path=/; Max-Age=${SESSION_HINT_MAX_AGE}; SameSite=Lax${secureCookieSuffix()}`;
}

function clearSessionHint(): void {
  if (typeof document === "undefined") return;
  document.cookie = `${SESSION_HINT_COOKIE}=; Path=/; Max-Age=0; SameSite=Lax${secureCookieSuffix()}`;
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = React.useState<User | null>(null);
  const [status, setStatus] = React.useState<AuthStatus>("loading");
  const [sessionExpired, setSessionExpired] = React.useState(false);
  // Incremented on every explicit auth transition so a slow bootstrap refresh
  // can never overwrite a newer login/logout result.
  const authEpoch = React.useRef(0);
  const applyTokens = React.useCallback((tokens: TokenResponse) => {
    authEpoch.current += 1;
    setSessionHint();
    setAccessToken(tokens.access_token);
    setUser(tokens.user);
    setStatus("authenticated");
    setSessionExpired(false);
  }, []);

  const clearSession = React.useCallback(
    (expired = false) => {
      authEpoch.current += 1;
      clearSessionHint();
      clearAccessToken();
      setUser(null);
      setStatus("unauthenticated");
      setSessionExpired(expired);
      queryClient.clear();
    },
    [queryClient],
  );

  // Boot with POST /auth/refresh: the refresh cookie is HttpOnly, so this is
  // the only way to know whether a session already exists.
  //
  // On a first visit to the login page there is no hint, so skip the request
  // (and the expected 401 in the browser console). A returning user with a
  // session still gets the hint and is redirected properly.
  //
  // Do not gate this on a "did I run?" ref: React StrictMode mounts, cleans up
  // and remounts effects in development. A cancelled flag from the first mount
  // combined with such a ref would leave status stuck on "loading". The
  // single-flight refresh in lib/api.ts de-duplicates the network call.
  React.useEffect(() => {
    let active = true;
    const epoch = authEpoch.current;

    if (
      typeof window !== "undefined" &&
      window.location.pathname.startsWith("/login") &&
      !hasSessionHint()
    ) {
      setStatus("unauthenticated");
      return;
    }

    refreshSession()
      .then((tokens) => {
        if (!active || authEpoch.current !== epoch) return;
        setSessionHint();
        setUser(tokens.user);
        setStatus("authenticated");
      })
      .catch(() => {
        if (!active || authEpoch.current !== epoch) return;
        clearSessionHint();
        setStatus("unauthenticated");
      });

    return () => {
      active = false;
    };
  }, []);

  // A refresh triggered by a 401 failed: the refresh cookie is gone/invalid.
  React.useEffect(() => {
    const onExpired = () => {
      clearSession(true);
    };
    window.addEventListener(SESSION_EXPIRED_EVENT, onExpired);
    return () => window.removeEventListener(SESSION_EXPIRED_EVENT, onExpired);
  }, [clearSession]);

  const login = React.useCallback(
    async (credentials: LoginRequest) => {
      const tokens = await api.post<TokenResponse>("/auth/login", credentials);
      authEpoch.current += 1;
      applyTokens(tokens);
      queryClient.clear();
      return tokens.user;
    },
    [applyTokens, queryClient],
  );

  const logout = React.useCallback(async () => {
    try {
      await api.post<void>("/auth/logout", undefined, { csrf: true });
    } catch {
      // The cookie is cleared server-side even on failure; local state must go
      // away regardless.
    } finally {
      clearSession(false);
    }
  }, [clearSession]);

  const refresh = React.useCallback(async () => {
    try {
      const tokens = await refreshSession();
      setSessionHint();
      setUser(tokens.user);
      setStatus("authenticated");
      return tokens.user;
    } catch {
      clearSession(true);
      return null;
    }
  }, [clearSession]);

  const forceSignOut = React.useCallback(() => {
    clearSession(false);
  }, [clearSession]);

  const clearSessionExpired = React.useCallback(
    () => setSessionExpired(false),
    [],
  );

  const value = React.useMemo<AuthContextValue>(
    () => ({
      user,
      status,
      isAuthenticated: status === "authenticated" && !!user,
      sessionExpired,
      login,
      logout,
      refresh,
      forceSignOut,
      clearSessionExpired,
    }),
    [
      user,
      status,
      sessionExpired,
      login,
      logout,
      refresh,
      forceSignOut,
      clearSessionExpired,
    ],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = React.useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}
