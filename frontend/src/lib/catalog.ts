// Which maps exist for each layer, read from the names of the published PMTiles files.
// A file is named <layer>__<map>.pmtiles, where <map> is YYYY-MM for a monthly layer,
// YYYY for a yearly one, or the layer id for a layer with one map (see publish in
// backend/src/green/pipeline.py).

export interface LayerMaps {
  names: string[]
  years: number[]
  monthly: boolean
}

export type Catalog = Map<string, LayerMaps>

const FILE = /^(.+?)__(.+)\.pmtiles$/
const MONTH = /^\d{4}-\d{2}$/
const YEAR = /^\d{4}/

export function readCatalog(files: string[]): Catalog {
  const names = new Map<string, string[]>()
  for (const file of files) {
    const [, layer, map] = FILE.exec(file) ?? []
    if (layer === undefined || map === undefined) continue
    names.set(layer, [...(names.get(layer) ?? []), map])
  }

  const catalog: Catalog = new Map()
  for (const [layer, maps] of names) {
    maps.sort()
    const dated = maps.filter((map) => YEAR.test(map))
    const years = [...new Set(dated.map((map) => Number(map.slice(0, 4))))]
    catalog.set(layer, {
      names: maps,
      years,
      monthly: maps.every((map) => MONTH.test(map)),
    })
  }
  return catalog
}

export interface When {
  year: number
  month: number
}

export interface Picked {
  name: string
  year?: number
  month?: number
}

/** The map to show for a chosen time: that year and month if it exists, else the nearest. */
export function pickMap(maps: LayerMaps, when: When): Picked | null {
  const [only] = maps.names
  if (only === undefined) return null
  if (maps.years.length === 0) return { name: only }
  if (!maps.monthly) {
    const year = nearest(maps.years, (y) => Math.abs(y - when.year))
    return { name: String(year), year }
  }
  const months = (w: When) => w.year * 12 + w.month - 1
  const name = nearest(maps.names, (map) =>
    Math.abs(months(monthOf(map)) - months(when))
  )
  return { name, ...monthOf(name) }
}

function monthOf(map: string): When {
  return { year: Number(map.slice(0, 4)), month: Number(map.slice(5, 7)) }
}

function nearest<T>(items: T[], distance: (item: T) => number): T {
  return items.reduce((best, item) =>
    distance(item) < distance(best) ? item : best
  )
}

/** PMTiles URL for one map; `site` is the absolute URL of the site root, ending in /. */
export function tileUrl(site: string, layerId: string, map: string): string {
  return `pmtiles://${site}tiles/${layerId}__${map}.pmtiles`
}
