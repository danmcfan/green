import 'maplibre-gl/dist/maplibre-gl.css'
import * as maplibregl from 'maplibre-gl'
import { Protocol } from 'pmtiles'
import { useEffect, useRef } from 'react'
import { layers } from '@/lib/layers'

const protocol = new Protocol()
maplibregl.addProtocol('pmtiles', protocol.tile)

const CONUS_BOUNDS: [number, number, number, number] = [-125, 24, -66.5, 49.5]

export default function App() {
  const container = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const map = new maplibregl.Map({
      container: container.current!,
      style: 'https://tiles.openfreemap.org/styles/positron',
      bounds: CONUS_BOUNDS,
    })
    return () => map.remove()
  }, [])

  return (
    <div className="relative h-dvh w-full">
      <div ref={container} className="absolute inset-0" />
      <aside className="absolute top-4 left-4 rounded-lg bg-background/90 p-4 text-sm shadow">
        <h1 className="font-semibold">Green</h1>
        <ul className="mt-2 text-muted-foreground">
          {layers.map((layer) => (
            <li key={layer.id}>{layer.name}</li>
          ))}
        </ul>
      </aside>
    </div>
  )
}
