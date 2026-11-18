export type Basemap = "satellite" | "streets";
export type RasterLayer = "rgb" | "false_color" | "ndvi" | "landcover" | "none";
export type VectorLayer = "landcover_polygons" | "mineral_tags" | "new_stockpiles" | "low_confidence" | "aoi";
export type Role = "baseline" | "target";

export const RASTER_LAYERS: { id: RasterLayer; label: string; hint: string }[] = [
  { id: "rgb", label: "True-color RGB", hint: "B04 · B03 · B02" },
  { id: "false_color", label: "False-color SWIR", hint: "B11 · B08 · B04" },
  { id: "ndvi", label: "NDVI heatmap", hint: "(NIR − Red) / (NIR + Red)" },
  { id: "landcover", label: "ML classification raster", hint: "Random Forest, 10 m" },
];

export const VECTOR_LAYERS: { id: VectorLayer; label: string; hint: string }[] = [
  { id: "landcover_polygons", label: "ML land classification polygons", hint: "Swipes with the comparison" },
  { id: "mineral_tags", label: "Hyperspectral mineral tags", hint: "SAM, target date" },
  { id: "new_stockpiles", label: "New stockpiles", hint: "Absent in baseline" },
  { id: "low_confidence", label: "Low-confidence zones", hint: "Model certainty < 70%" },
  { id: "aoi", label: "AOI boundary", hint: "" },
];

/** Categorical slots 1-4 (dark-surface steps), assigned to minerals in a fixed order; validated for CVD separation. */
export const MINERAL_COLORS: Record<string, string> = {
  Coal: "#3987e5",
  "Hematite / Iron Ore": "#d95926",
  "Kaolinite / Clay Tailings": "#199e70",
  "Sandstone / Shale Overburden": "#c98500",
};
export const mineralColor = (name: string) => MINERAL_COLORS[name] ?? "#8a8a85";

export const BASEMAPS: Record<Basemap, { url: string; attribution: string; maxNativeZoom: number }> = {
  satellite: {
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attribution: "Imagery &copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    maxNativeZoom: 18,
  },
  streets: {
    url: "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    maxNativeZoom: 19,
  },
};
export const SATELLITE_LABELS_URL =
  "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";
