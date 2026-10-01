import type { Identity } from "../api";

type Props = {
  identities: Identity[];
  current: Identity | null;
  onChange: (identityId: string) => void;
};

export function IdentitySwitcher({ identities, current, onChange }: Props) {
  return (
    <label className="identity-switcher">
      <span>Demo identity — no real login</span>
      <select value={current?.id ?? ""} onChange={(event) => onChange(event.target.value)}>
        {current === null && <option value="">Choose…</option>}
        {identities.map((identity) => (
          <option key={identity.id} value={identity.id}>
            {identity.name} ({identity.role})
          </option>
        ))}
      </select>
    </label>
  );
}
