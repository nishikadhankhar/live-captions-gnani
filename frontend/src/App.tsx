import { useEffect, useState } from "react";
import Home from "./screens/Home";
import Speaker from "./screens/Speaker";
import Attendee from "./screens/Attendee";

// Routes:  /  start an event   ·   /s/CODE  speaker screen   ·   /e/CODE  attendee (from the QR)
export function go(path: string) {
  window.history.pushState({}, "", path);
  window.dispatchEvent(new PopStateEvent("popstate"));
}

export default function App() {
  const [path, setPath] = useState(window.location.pathname);
  useEffect(() => {
    const on = () => setPath(window.location.pathname);
    window.addEventListener("popstate", on);
    return () => window.removeEventListener("popstate", on);
  }, []);

  const speaker = path.match(/^\/s\/([A-Za-z0-9]{4,8})\/?$/);
  const attendee = path.match(/^\/e\/([A-Za-z0-9]{4,8})\/?$/);
  if (speaker) return <Speaker code={speaker[1].toUpperCase()} />;
  if (attendee) return <Attendee code={attendee[1].toUpperCase()} />;
  return <Home />;
}
