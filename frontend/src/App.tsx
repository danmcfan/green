import { PanelLeft } from 'lucide-react'
import { useEffect, useState } from 'react'
import Controls from '@/components/controls'
import Legend from '@/components/legend'
import MapView from '@/components/map'
import { Button } from '@/components/ui/button'
import { Separator } from '@/components/ui/separator'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
  SheetTrigger,
} from '@/components/ui/sheet'
import { type Catalog, pickMap, readCatalog, tileUrl, type When } from '@/lib/catalog'
import { layers } from '@/lib/layers'

const SITE = new URL(import.meta.env.BASE_URL, window.location.href).href
// July: most of the country is near its greenest.
const DEFAULT_MONTH = 7

export default function App() {
  const [catalog, setCatalog] = useState<Catalog | null>(null)
  const [layerId, setLayerId] = useState('observed_ndvi')
  const [chosen, setChosen] = useState<When | null>(null)

  useEffect(() => {
    fetch(`${SITE}tiles/index.json`)
      .then((response) => (response.ok ? response.json() : []))
      .catch(() => [])
      .then((files: string[]) => setCatalog(readCatalog(files)))
  }, [])

  const layer = layers.find((l) => l.id === layerId)!
  const when = chosen ?? latest(catalog)
  const maps = catalog?.get(layerId)
  const picked = maps && when ? pickMap(maps, when) : null
  const url = picked ? tileUrl(SITE, layerId, picked.name) : null
  const setWhen = (change: Partial<When>) => when && setChosen({ ...when, ...change })

  const heading = (
    <div>
      <h1 className="font-heading text-lg font-semibold">Green</h1>
      <p className="text-sm text-muted-foreground">
        How green the land is, and how green soil and climate predict it should be.
      </p>
    </div>
  )
  const title = (
    <p className="text-sm font-medium">
      {layer.name}
      {picked?.year !== undefined && (
        <span className="text-muted-foreground"> · {picked.name}</span>
      )}
    </p>
  )
  const controls = catalog && (
    <Controls
      catalog={catalog}
      layer={layer}
      picked={picked}
      setLayer={setLayerId}
      setWhen={setWhen}
    />
  )
  const empty = catalog?.size === 0 && (
    <p className="text-sm text-muted-foreground">
      No maps found. Run the pipeline and <code>task tiles:local</code>, or publish a Release.
    </p>
  )

  return (
    <div className="flex h-dvh w-full flex-col gap-3 p-3 lg:grid lg:grid-cols-4 lg:gap-4 lg:p-4">
      <header className="flex items-center gap-3 lg:hidden">
        <Sheet>
          <SheetTrigger render={<Button size="icon" variant="outline" />}>
            <PanelLeft />
            <span className="sr-only">Layers</span>
          </SheetTrigger>
          <SheetContent side="top" className="p-4 pb-8">
            <SheetHeader className="p-0">
              <SheetTitle>Green</SheetTitle>
              <SheetDescription>Choose a layer and a time.</SheetDescription>
            </SheetHeader>
            {empty}
            {controls}
          </SheetContent>
        </Sheet>
        <div className="flex min-w-0 flex-1 flex-col gap-1">
          {title}
          <Legend layer={layer} />
        </div>
      </header>

      <main className="min-h-0 flex-1 lg:col-span-3">
        <MapView url={url} />
      </main>

      <aside className="hidden flex-col gap-4 overflow-y-auto p-2 lg:flex">
        {heading}
        <Separator />
        {title}
        <Legend layer={layer} />
        <Separator />
        {empty}
        {controls}
      </aside>
    </div>
  )
}

/** The latest year with any map, in DEFAULT_MONTH; null until the catalog is loaded or if empty. */
function latest(catalog: Catalog | null): When | null {
  const years = [...(catalog?.values() ?? [])].flatMap((maps) => maps.years)
  return years.length ? { year: Math.max(...years), month: DEFAULT_MONTH } : null
}
