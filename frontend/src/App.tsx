import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Identity } from "./api";
import { IdentitySwitcher } from "./components/IdentitySwitcher";
import { KycPage } from "./kyc/KycPage";

export default function App() {
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [user, setUser] = useState<Identity | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<Identity[]>("/api/demo/identities")
      .then(setIdentities)
      .catch((err: Error) => setError(err.message));
    api<Identity>("/api/demo/session")
      .then(setUser)
      .catch((err: Error) => {
        if (!(err instanceof ApiError && err.status === 401)) setError(err.message);
      })
      .finally(() => setChecking(false));
  }, []);

  const switchIdentity = useCallback(async (identityId: string) => {
    try {
      setUser(await api<Identity>("/api/demo/session", { method: "POST", body: { identity: identityId } }));
      setError(null);
    } catch (err) {
      setError((err as Error).message);
    }
  }, []);

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">Ops internal tools <span className="muted">(local demo, fictional data)</span></div>
        <nav className="nav">
          <a href="#kyc" className="active">KYC review</a>
        </nav>
        <IdentitySwitcher identities={identities} current={user} onChange={switchIdentity} />
      </header>
      {error && <div className="state state-error banner" role="alert">{error}</div>}
      <main>
        {checking ? (
          <div className="state">Loading…</div>
        ) : user === null ? (
          <div className="state">Choose a demo identity to continue.</div>
        ) : (
          <KycPage key={user.id} user={user} />
        )}
      </main>
    </div>
  );
}
