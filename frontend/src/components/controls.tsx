import { CloudRain, Leaf, Shovel, Wheat } from 'lucide-react'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import type { Catalog, Picked, When } from '@/lib/catalog'
import { GROUPS, type GroupId, groupOf, type LayerDefinition, layers } from '@/lib/layers'

const ICONS: Record<GroupId, typeof Leaf> = {
  soil: Shovel,
  climate: CloudRain,
  ndvi: Leaf,
  crops: Wheat,
}

const MONTHS = Array.from({ length: 12 }, (_, i) =>
  new Date(2000, i).toLocaleString('en-US', { month: 'long' }),
)

export default function Controls({
  catalog,
  layer,
  picked,
  setLayer,
  setWhen,
}: {
  catalog: Catalog
  layer: LayerDefinition
  picked: Picked | null
  setLayer: (id: string) => void
  setWhen: (change: Partial<When>) => void
}) {
  const group = groupOf(layer)
  const inGroup = layers.filter((l) => groupOf(l) === group)
  const maps = catalog.get(layer.id)
  const years = maps?.years ?? []
  const year = picked?.year
  const month = picked?.month

  return (
    <div className="flex w-full flex-col gap-6">
      <Tabs
        value={group}
        onValueChange={(value) => {
          const choices = layers.filter((l) => groupOf(l) === value)
          setLayer((choices.find((l) => catalog.has(l.id)) ?? choices[0]).id)
        }}
      >
        <TabsList className="grid w-full grid-cols-4">
          {GROUPS.map(({ id, label }) => {
            const Icon = ICONS[id]
            return (
              <TabsTrigger key={id} value={id} aria-label={label} title={label}>
                <Icon />
                <span className="sr-only sm:not-sr-only lg:sr-only xl:not-sr-only">{label}</span>
              </TabsTrigger>
            )
          })}
        </TabsList>
      </Tabs>

      <div className="flex flex-col gap-2">
        <Label>Layer</Label>
        <Select
          value={layer.id}
          onValueChange={(value) => value && setLayer(value)}
          items={inGroup.map((l) => ({ value: l.id, label: l.name }))}
        >
          <SelectTrigger className="w-full" aria-label="Layer">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {inGroup.map((l) => (
              <SelectItem key={l.id} value={l.id} disabled={!catalog.has(l.id)}>
                {l.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {year !== undefined && (
        <div className="flex flex-col gap-3">
          <div className="flex justify-between">
            <Label>Year</Label>
            <span className="text-sm tabular-nums">{year}</span>
          </div>
          {years.length > 1 && (
            <Slider
              aria-label="Year"
              min={years[0]}
              max={years.at(-1)}
              value={[year]}
              // Keep the month on screen, so both sliders move from what the map shows.
              onValueChange={(value) => setWhen({ year: first(value), ...(month && { month }) })}
            />
          )}
        </div>
      )}

      {year !== undefined && month !== undefined && (
        <div className="flex flex-col gap-3">
          <div className="flex justify-between">
            <Label>Month</Label>
            <span className="text-sm">{MONTHS[month - 1]}</span>
          </div>
          <Slider
            aria-label="Month"
            min={1}
            max={12}
            value={[month]}
            onValueChange={(value) => setWhen({ year, month: first(value) })}
          />
        </div>
      )}

      {layer.id === 'crop_effect' && (
        <p className="text-sm text-muted-foreground">
          The Crop effect only means something where it is larger than the model&apos;s error on
          natural land nearby.{' '}
          <LayerLink onClick={() => setLayer('crop_effect_error')}>Show that error</LayerLink>
        </p>
      )}
      {layer.id === 'crop_effect_error' && (
        <p className="text-sm text-muted-foreground">
          How wrong Predicted NDVI is on natural land next to farm land, in each spatial block over
          every month: the largest error on places, years, or both that the model did not see. A
          Crop effect smaller than this cannot be told apart from model error.{' '}
          <LayerLink onClick={() => setLayer('crop_effect')}>Show the Crop effect</LayerLink>
        </p>
      )}

      {!maps && (
        <p className="text-sm text-muted-foreground">No maps have been published for this layer.</p>
      )}
    </div>
  )
}

function LayerLink({ onClick, children }: { onClick: () => void; children: string }) {
  return (
    <button type="button" className="text-foreground underline underline-offset-4" onClick={onClick}>
      {children}
    </button>
  )
}

function first(value: number | readonly number[]): number {
  return typeof value === 'number' ? value : value[0]
}
