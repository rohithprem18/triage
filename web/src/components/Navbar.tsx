import type { Route, Theme } from "../hooks";
import { ThemeToggle } from "./ThemeToggle";
import type { Health } from "../types";

const LINKS: { route: Route; label: string }[] = [
  { route: "incidents", label: "Incidents" },
  { route: "system", label: "System" },
  { route: "runbooks", label: "Runbooks" },
  { route: "benchmark", label: "Benchmark" },
];

export function Logo({ size = 22 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true">
      <rect x="0.5" y="0.5" width="31" height="31" rx="8" fill="none" stroke="currentColor" opacity="0.35" />
      <path d="M16 8l8.5 15h-17z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />
      <path d="M16 14v4.5M16 20.6v.4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

export function Navbar({ route, incident, health, healthError, theme, onToggleTheme }: { route: Route; incident: string | null; health: Health | null; healthError: boolean; theme: Theme; onToggleTheme: () => void }) {
  const state = healthError ? "bad" : health ? "good" : "warn";
  const label = healthError ? "API offline" : health ? "Simulated environment" : "Connecting";
  return (
    <header className="navbar">
      <div className="nav-inner">
        <a className="brand" href="#/incidents" aria-label="Triage home">
          <Logo />
          <span>Triage</span>
        </a>
        <nav className="nav-links" aria-label="Sections">
          {LINKS.map((l) => (
            <a key={l.route} href={`#/${l.route}${incident && (l.route === "incidents" || l.route === "system") ? `?i=${incident}` : ""}`}
               className={route === l.route ? "active" : undefined} aria-current={route === l.route ? "page" : undefined}>
              {l.label}
            </a>
          ))}
        </nav>
        <div className="nav-right">
          <span className={`status ${state}`} role="status" title="Incidents run against a deterministic simulation of an e-commerce system">
            <span className="dot" aria-hidden="true" />
            {label}
          </span>
          <ThemeToggle theme={theme} onToggle={onToggleTheme} />
          <a className="pill sm" href="https://github.com/rohithprem18/triage" target="_blank" rel="noopener noreferrer">GitHub</a>
        </div>
      </div>
    </header>
  );
}
