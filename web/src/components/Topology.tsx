import type { ServiceHealth } from "../types";

// fixed layered layout: edge -> orchestration -> services -> data / external
const POS: Record<string, [number, number]> = {
  gateway: [70, 170],
  checkout: [240, 90],
  cart: [240, 250],
  catalog: [240, 330],
  payments: [420, 40],
  inventory: [420, 150],
  psp: [600, 40],
  postgres: [600, 230],
  redis: [420, 290],
};
const W = 150, H = 44;
const COLOR = { healthy: "var(--good)", degraded: "var(--warn)", unhealthy: "var(--bad)" };

export function Topology({ services, topology, selected, onSelect }: {
  services: ServiceHealth[]; topology: Record<string, string[]>; selected: string | null; onSelect: (s: string) => void;
}) {
  const health = Object.fromEntries(services.map((s) => [s.service, s]));
  return (
    <svg className="topo" viewBox="0 0 760 380" role="img" aria-label="Service dependency map coloured by health">
      {Object.entries(topology).flatMap(([from, tos]) =>
        tos.map((to) => {
          const [x1, y1] = POS[from], [x2, y2] = POS[to];
          return <line key={`${from}-${to}`} className="edge" x1={x1 + W} y1={y1 + H / 2} x2={x2} y2={y2 + H / 2} />;
        }),
      )}
      {Object.entries(POS).map(([name, [x, y]]) => {
        const h = health[name];
        const color = h ? COLOR[h.status] : "var(--hairline)";
        return (
          <g key={name} className="node" transform={`translate(${x},${y})`} onClick={() => onSelect(name)}
             role="button" aria-label={`${name}: ${h?.status ?? "unknown"}`}>
            <rect width={W} height={H} rx="8" stroke={selected === name ? "var(--ink)" : color}
                  strokeWidth={selected === name ? 2 : 1.5} />
            <circle cx="16" cy={H / 2} r="4" fill={color} />
            <text x="28" y="19">{name}</text>
            <text className="sub" x="28" y="34">
              {h ? `${h.error_rate_pct.toFixed(1)}% err · ${h.p95_ms >= 1000 ? `${(h.p95_ms / 1000).toFixed(1)}s` : `${Math.round(h.p95_ms)}ms`}` : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function Sparkline({ values, color = "var(--sunset)", height = 28 }: { values: number[]; color?: string; height?: number }) {
  if (!values.length) return null;
  const max = Math.max(...values), min = Math.min(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => `${(i / (values.length - 1)) * 100},${height - 2 - ((v - min) / span) * (height - 4)}`).join(" ");
  return (
    <svg viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" style={{ width: "100%", height }} aria-hidden="true">
      <polyline fill="none" stroke={color} strokeWidth="1.5" vectorEffect="non-scaling-stroke" points={pts} />
    </svg>
  );
}
