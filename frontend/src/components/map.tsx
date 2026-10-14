import "maplibre-gl/dist/maplibre-gl.css"
import { LocateFixed, Minus, Plus } from "lucide-react"
import * as maplibregl from "maplibre-gl"
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?url"
import { PMTiles, Protocol } from "pmtiles"
import { useEffect, useRef, useState } from "react"
import { useTheme } from "@/components/theme-provider"
import { Button } from "@/components/ui/button"
import { ButtonGroup } from "@/components/ui/button-group"
import { Skeleton } from "@/components/ui/skeleton"
import { type Region, regionOutline } from "@/lib/region"

// MapLibre finds its worker next to its own module, which Vite moves; point it at the file.
maplibregl.setWorkerUrl(workerUrl)
const protocol = new Protocol()
maplibregl.addProtocol("pmtiles", protocol.tile)

const CONUS_BOUNDS: [number, number, number, number] = [-125, 24, -66.5, 49.5]
const SOURCE = "layer"
const OUTLINE = "region-outline"
const BASEMAPS = {
  light: "https://tiles.openfreemap.org/styles/positron",
  dark: "https://tiles.openfreemap.org/styles/dark",
}
// The theme's foreground; MapLibre paints with literal colors, not CSS variables.
const OUTLINE_COLORS = { light: "#171717", dark: "#fafafa" }

/** The basemap with one raster PMTiles map drawn under its labels; `url` is a pmtiles:// URL. */
export default function MapView({ url }: { url: string | null }) {
  const container = useRef<HTMLDivElement>(null)
  const [map, setMap] = useState<maplibregl.Map | null>(null)
  const [region, setRegion] = useState<Region | null>(null)
  const fitted = useRef(false)
  const { resolved } = useTheme()
  // The theme whose basemap the map shows, or is loading.
  const shown = useRef(resolved)
  // True between setStyle and style.load, when layers cannot be added.
  const switching = useRef(false)
  // Bumped each time a new basemap finishes loading, which drops the raster layer.
  const [styles, setStyles] = useState(0)

  useEffect(() => {
    if (!map || shown.current === resolved) return
    shown.current = resolved
    switching.current = true
    map.once("style.load", () => {
      switching.current = false
      setStyles((n) => n + 1)
    })
    map.setStyle(BASEMAPS[resolved])
  }, [map, resolved])

  // Declared before the effect that creates the map, so its cleanup runs before map.remove().
  useEffect(() => {
    if (!map || switching.current || url === null) return
    // Under the Region's outline if it is drawn, else under the basemap's labels.
    const above = map.getLayer(OUTLINE) ? OUTLINE : firstLabelLayer(map)
    map.addSource(SOURCE, { type: "raster", url, tileSize: 256 })
    map.addLayer(
      {
        id: SOURCE,
        type: "raster",
        source: SOURCE,
        paint: { "raster-opacity": 0.8, "raster-resampling": "nearest" },
      },
      above
    )
    let live = true
    // Pipeline output can cover a small Region, so show the first map's Region once.
    if (!fitted.current) {
      const archive = new PMTiles(url.slice("pmtiles://".length))
      protocol.add(archive)
      void archive.getHeader().then((h) => {
        // A cleanup before the header arrived leaves the fit to the next map.
        if (!live) return
        fitted.current = true
        setRegion(h)
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
    if (!map || switching.current || !region) return
    map.addSource(OUTLINE, { type: "geojson", data: regionOutline(region) })
    map.addLayer(
      {
        id: OUTLINE,
        type: "line",
        source: OUTLINE,
        paint: {
          "line-color": OUTLINE_COLORS[shown.current],
          "line-opacity": 0.6,
          "line-width": 1.5,
          "line-dasharray": [2, 2],
        },
      },
      firstLabelLayer(map)
    )
    return () => {
      if (map.getLayer(OUTLINE)) map.removeLayer(OUTLINE)
      if (map.getSource(OUTLINE)) map.removeSource(OUTLINE)
    }
  }, [map, region, styles])

  useEffect(() => {
    const element = container.current
    if (!element) return
    const map = new maplibregl.Map({
      container: element,
      style: BASEMAPS[shown.current],
      bounds: CONUS_BOUNDS,
      attributionControl: false,
      // A flat data map: north stays up, so there is no compass to bring it back.
      dragRotate: false,
      pitchWithRotate: false,
      touchPitch: false,
    })
    map.touchZoomRotate.disableRotation()
    map.keyboard.disableRotation()
    // A short line, always shown, as OpenStreetMap asks; not a box that opens on load.
    map.addControl(
      new maplibregl.AttributionControl({ compact: false }),
      "bottom-right"
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
      {map && <MapControls map={map} />}
    </div>
  )
}

/** The basemap's lowest label layer, which data layers go under; undefined puts them on top. */
function firstLabelLayer(map: maplibregl.Map): string | undefined {
  return map.getStyle().layers.find((layer) => layer.type === "symbol")?.id
}

/** Zoom and locate, as shadcn buttons on the same glass as the panel. */
function MapControls({ map }: { map: maplibregl.Map }) {
  const [locating, setLocating] = useState(false)
  const marker = useRef<maplibregl.Marker | null>(null)
  useEffect(
    () => () => {
      marker.current?.remove()
    },
    []
  )
  const locate = () => {
    setLocating(true)
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => {
        setLocating(false)
        const here: [number, number] = [coords.longitude, coords.latitude]
        marker.current ??= new maplibregl.Marker()
        marker.current.setLngLat(here).addTo(map)
        map.flyTo({ center: here, zoom: Math.max(map.getZoom(), 8) })
      },
      () => setLocating(false)
    )
  }

  return (
    <div className="absolute bottom-4 left-4 rounded-xl glass p-1">
      <ButtonGroup orientation="vertical" aria-label="Map controls">
        <Button size="icon" variant="ghost" onClick={() => map.zoomIn()}>
          <Plus />
          <span className="sr-only">Zoom in</span>
        </Button>
        <Button size="icon" variant="ghost" onClick={() => map.zoomOut()}>
          <Minus />
          <span className="sr-only">Zoom out</span>
        </Button>
        {"geolocation" in navigator && (
          <Button
            size="icon"
            variant="ghost"
            disabled={locating}
            onClick={locate}
          >
            <LocateFixed />
            <span className="sr-only">Show my location</span>
          </Button>
        )}
      </ButtonGroup>
    </div>
  )
}
