import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken, setUnauthorisedHandler } from "../api/client";
import type { Me, Role, TokenOut } from "../api/types";

type LoginResult = { mfaToken: string } | { me: Me };

interface AuthState {
  me: Me | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<LoginResult>;
  loginMfa: (mfaToken: string, code: string) => Promise<Me>;
  adoptToken: (token: string) => Promise<Me>;
  logout: () => void;
  refresh: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function homeFor(me: Me): string {
  if (me.must_change_password) return "/change-password";
  const homes: Record<Role, string> = {
    customer: "/search",
    business: "/business",
    driver: "/driver",
    admin: "/admin",
  };
  return homes[me.role];
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [loading, setLoading] = useState(Boolean(getToken()));

  const logout = useCallback(() => {
    setToken(null);
    setMe(null);
  }, []);

  const refresh = useCallback(async () => {
    if (!getToken()) {
      setMe(null);
      setLoading(false);
      return;
    }
    try {
      setMe(await api<Me>("/api/auth/me"));
    } catch {
      logout();
    } finally {
      setLoading(false);
    }
  }, [logout]);

  useEffect(() => {
    setUnauthorisedHandler(logout); // expired or revoked session → back to login
    void refresh();
  }, [refresh, logout]);

  const adoptToken = useCallback(async (token: string) => {
    setToken(token);
    const who = await api<Me>("/api/auth/me");
    setMe(who);
    return who;
  }, []);

  const login = useCallback(
    async (email: string, password: string): Promise<LoginResult> => {
      const form = new URLSearchParams({ username: email, password });
      const out = await api<TokenOut>("/api/auth/login", { form });
      if (out.mfa_required && out.mfa_token) return { mfaToken: out.mfa_token };
      return { me: await adoptToken(out.access_token!) };
    },
    [adoptToken],
  );

  const loginMfa = useCallback(
    async (mfaToken: string, code: string) => {
      const out = await api<TokenOut>("/api/auth/login/mfa", {
        json: { mfa_token: mfaToken, code },
      });
      return adoptToken(out.access_token!);
    },
    [adoptToken],
  );

  return (
    <AuthContext.Provider value={{ me, loading, login, loginMfa, adoptToken, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}
