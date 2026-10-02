import { useCallback, useEffect, useState } from "react";
import { api, ApiError, type Identity } from "./api";
import { IdentitySwitcher } from "./components/IdentitySwitcher";
import { KycPage } from "./kyc/KycPage";
import { ChargebacksPage } from "./chargebacks/ChargebacksPage";
import { RefundsPage } from "./refunds/RefundsPage";
import { WorkPage } from "./work/WorkPage";
import { ApprovalsPage } from "./approvals/ApprovalsPage";
import { AuditPage } from "./audit/AuditPage";

type Access = "all" | "employee" | "supervisor";
const PAGES = [
  { id: "kyc", label: "KYC review", access: "all" },
  { id: "refunds", label: "Refunds", access: "all" },
  { id: "chargebacks", label: "Chargebacks", access: "all" },
  { id: "mine", label: "My Work", access: "employee" },
  { id: "work", label: "Work List", access: "supervisor" },
  { id: "approvals", label: "Approvals", access: "supervisor" },
  { id: "audit", label: "Audit Log", access: "supervisor" },
] as const satisfies readonly { id: string; label: string; access: Access }[];
type PageId = (typeof PAGES)[number]["id"];
type Route = { page: PageId; recordId: string | null };

/** `#page` or `#page/RECORD-ID` (record links between workflows). */
function routeFromHash(): Route {
  const [name, id] = window.location.hash.slice(1).split("/", 2);
  const page = PAGES.find((p) => p.id === name)?.id ?? "kyc";
  return { page, recordId: id ? decodeURIComponent(id) : null };
}

export default function App() {
  const [identities, setIdentities] = useState<Identity[]>([]);
  const [user, setUser] = useState<Identity | null>(null);
  const [checking, setChecking] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [route, setRoute] = useState<Route>(routeFromHash);
  const { page, recordId } = route;

  useEffect(() => {
    const onHashChange = () => setRoute(routeFromHash());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

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
          {PAGES.filter(
            (p) =>
              p.access === "all" ||
              (p.access === "employee" && user?.can_mutate) ||
              (p.access === "supervisor" && user?.can_supervise),
          ).map((p) => (
            <a key={p.id} href={`#${p.id}`} className={page === p.id ? "active" : undefined}>
              {p.label}
            </a>
          ))}
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
          (() => {
            const key = `${user.id}-${recordId ?? ""}`;
            if (page === "kyc") return <KycPage key={key} user={user} initialId={recordId} />;
            if (page === "refunds") return <RefundsPage key={key} user={user} initialId={recordId} />;
            if (page === "mine") return <WorkPage key={key} user={user} mode="mine" />;
            if (page === "work") return <WorkPage key={key} user={user} mode="all" />;
            if (page === "approvals") return <ApprovalsPage key={key} user={user} />;
            if (page === "audit") return <AuditPage key={key} user={user} />;
            return <ChargebacksPage key={key} user={user} initialId={recordId} />;
          })()
        )}
      </main>
    </div>
  );
}
