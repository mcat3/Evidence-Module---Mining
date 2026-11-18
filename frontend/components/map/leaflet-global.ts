/**
 * leaflet-geoman is a classic Leaflet plugin: it patches the global `L` (and adds its init hook to L.Map) at import
 * time. Bundled Leaflet is an ES module with no global, so expose it before the plugin is evaluated.
 */
import L from "leaflet";

declare global {
  interface Window {
    L: typeof L;
  }
}

if (typeof window !== "undefined") window.L = L;

export default L;
