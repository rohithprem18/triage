import { useEffect } from "react";
import { api } from "./api";
import { Navbar } from "./components/Navbar";
import { useLoad, useRoute } from "./hooks";
import { Benchmark } from "./views/Benchmark";
import { Incidents } from "./views/Incidents";
import { Runbooks } from "./views/Runbooks";
import { System } from "./views/System";

const TITLES = { incidents: "Incidents", system: "System", runbooks: "Runbooks", benchmark: "Benchmark" };

export default function App() {
  const { route, incident, go } = useRoute();
  const [health, healthError] = useLoad((s) => api.health(s), []);

  useEffect(() => {
    document.title = `${TITLES[route]} · Triage`;
  }, [route]);

  return (
    <>
      <Navbar route={route} incident={incident} health={health} healthError={healthError} />
      <main key={route}>
        {route === "incidents" && <Incidents selected={incident} onSelect={(c) => go("incidents", c)} health={health} />}
        {route === "system" && <System incident={incident} onIncident={(c) => go("system", c)} />}
        {route === "runbooks" && <Runbooks />}
        {route === "benchmark" && <Benchmark />}
      </main>
    </>
  );
}
