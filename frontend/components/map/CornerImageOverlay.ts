import L from "leaflet";

export interface Corners {
  topLeft: L.LatLngExpression;
  topRight: L.LatLngExpression;
  bottomLeft: L.LatLngExpression;
}

/**
 * Image overlay pinned by three corners and placed with a CSS affine matrix.
 *
 * Pipeline PNGs are rendered on a UTM grid, which is rotated against lon/lat by the meridian convergence (~0.5° at
 * Gevra). L.ImageOverlay can only stretch an image over an axis-aligned lat/lon box, which shears it by up to ~40 m
 * at the corners; mapping the three real corners keeps rasters registered with the vector polygons.
 */
export class CornerImageOverlay extends L.Layer {
  private img?: HTMLImageElement;
  private corners: { tl: L.LatLng; tr: L.LatLng; bl: L.LatLng };

  constructor(
    private url: string,
    corners: Corners,
    public options: L.LayerOptions & { opacity?: number; className?: string; alt?: string } = {},
  ) {
    super(options);
    this.corners = { tl: L.latLng(corners.topLeft), tr: L.latLng(corners.topRight), bl: L.latLng(corners.bottomLeft) };
  }

  onAdd(map: L.Map): this {
    const img = L.DomUtil.create("img", "leaflet-image-layer tp-corner-image") as HTMLImageElement;
    if (map.options.zoomAnimation && L.Browser.any3d) L.DomUtil.addClass(img, "leaflet-zoom-animated");
    if (this.options.className) L.DomUtil.addClass(img, this.options.className);
    img.alt = this.options.alt ?? "";
    img.draggable = false;
    img.style.transformOrigin = "0 0";
    img.style.visibility = "hidden";
    img.onload = () => {
      img.style.visibility = "";
      this.reset();
    };
    img.src = this.url;
    this.img = img;
    this.setOpacity(this.options.opacity ?? 1);
    this.getPane()!.appendChild(img);
    this.reset();
    return this;
  }

  onRemove(): this {
    this.img?.remove();
    this.img = undefined;
    return this;
  }

  getEvents(): { [name: string]: L.LeafletEventHandlerFn } {
    return { zoomanim: this.animateZoom as L.LeafletEventHandlerFn, viewreset: this.reset, zoom: this.reset };
  }

  setOpacity(opacity: number): this {
    this.options.opacity = opacity;
    if (this.img) this.img.style.opacity = String(opacity);
    return this;
  }

  getBounds(): L.LatLngBounds {
    const { tl, tr, bl } = this.corners;
    const br = L.latLng(tr.lat + bl.lat - tl.lat, tr.lng + bl.lng - tl.lng);
    return L.latLngBounds([tl, tr, bl, br]);
  }

  private place(project: (ll: L.LatLng) => L.Point) {
    const img = this.img;
    if (!img || !img.naturalWidth) return;
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    const p0 = project(this.corners.tl);
    const p1 = project(this.corners.tr);
    const p2 = project(this.corners.bl);
    img.style.width = `${w}px`;
    img.style.height = `${h}px`;
    img.style.transform =
      `matrix(${(p1.x - p0.x) / w}, ${(p1.y - p0.y) / w}, ${(p2.x - p0.x) / h}, ${(p2.y - p0.y) / h}, ${p0.x}, ${p0.y})`;
  }

  private reset = () => {
    if (this._map) this.place((ll) => this._map.latLngToLayerPoint(ll));
  };

  private animateZoom = (e: L.ZoomAnimEvent) => {
    const map = this._map as L.Map & {
      _latLngToNewLayerPoint(ll: L.LatLng, zoom: number, center: L.LatLng): L.Point;
    };
    this.place((ll) => map._latLngToNewLayerPoint(ll, e.zoom, e.center));
  };
}
