import "maplibre-gl/dist/maplibre-gl.css"
import * as maplibregl from "maplibre-gl"
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url"
import { PMTiles, Protocol } from "pmtiles"
import { useEffect, useRef, useState } from "react"
import { useTheme } from "@/components/theme-provider"
import { Skeleton } from "@/components/ui/skeleton"

// MapLibre finds its worker next to its own module, which Vite moves; point it at the file.
maplibregl.setWorkerUrl(workerUrl)
const protocol = new Protocol()
maplibregl.addProtocol("pmtiles", protocol.tile)

const CONUS_BOUNDS: [number, number, number, number] = [-125, 24, -66.5, 49.5]
const SOURCE = "layer"
const BASEMAPS = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
}

/** The basemap with one raster PMTiles map drawn under its labels; `url` is a pmtiles:// URL. */
export default function MapView({ url }: { url: string | null }) {
  const container = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<maplibregl.Map | null>(null)
  const fitted = useRef(false)
  const { resolved } = useTheme()
  const basemap = BASEMAPS[resolved]
  const shown = useRef(basemap)
  // Bumped each time a new basemap finishes loading, which drops the raster layer.
  const [styles, setStyles] = useState(0)

  useEffect(() => {
    if (!map || shown.current === basemap) return
    shown.current = basemap
    map.once("style.load", () => setStyles((n) => n + 1))
    map.setStyle(basemap)
  }, [map, basemap])

  // Declared before the effect that creates the map, so its cleanup runs before map.remove().
  useEffect(() => {
    if (!map || url === null) return
    const labels = map
      .getStyle()
      .layers.find((layer) => layer.type === "symbol")?.id
    map.addSource(SOURCE, { type: "raster", url, tileSize: 256 })
    map.addLayer(
      {
        id: SOURCE,
        type: "raster",
        source: SOURCE,
        paint: { "raster-opacity": 0.8, "raster-resampling": "nearest" },
      },
      labels
    )
    let live = true
    // Pipeline output can cover a small region, so show the first map's extent once.
    if (!fitted.current) {
      fitted.current = true
      const archive = new PMTiles(url.slice("pmtiles://".length))
      protocol.add(archive)
      void archive.getHeader().then((h) => {
        if (live)
          map.fitBounds([h.minLon, h.minLat, h.maxLon, h.maxLat], {
            padding: 40,
            duration: 0,
          })
      })
    }
    return () => {
      live = false
      // A basemap change has already removed them.
      if (map.getLayer(SOURCE)) map.removeLayer(SOURCE)
      if (map.getSource(SOURCE)) map.removeSource(SOURCE)
    }
  }, [map, url, styles])

  useEffect(() => {
    const element = container.current
    if (!element) return
    const map = new maplibregl.Map({
      container: element,
      style: shown.current,
      bounds: CONUS_BOUNDS,
      attributionControl: false,
    })
    // Bottom left, clear of the floating panel on the right.
    map.addControl(new maplibregl.NavigationControl(), "bottom-left")
    map.addControl(new maplibregl.GeolocateControl({}), "bottom-left")
    map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-left"
    )
    map.on("load", () => setMap(map))
    return () => {
      setMap(null)
      map.remove()
    }
  }, [])

  return (
    <div className="relative h-full w-full">
      <div ref={container} className="h-full w-full" />
      {!map && <Skeleton className="absolute inset-0 rounded-none" />}
    </div>
  )
}
