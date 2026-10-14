import type { LayerDefinition } from "@/lib/layers"

const number = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 })

// Colors are spread evenly over the range, as the pipeline draws them (tiles.py colorize).
export default function Legend({ layer }: { layer: LayerDefinition }) {
  if (layer.categories) {
    return (
      <ul className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3 lg:grid-cols-2">
        {layer.categories.map((name, i) => (
          <li key={name} className="flex items-center gap-2">
            <span
              className="size-3 shrink-0 rounded-sm border bg-(--swatch)"
              style={{ "--swatch": layer.colors[i] }}
            />
            {name}
          </li>
        ))}
      </ul>
    )
  }

  const [min, max] = layer.range
  return (
    <div className="flex flex-col gap-1">
      <div
        className="h-4 w-full rounded-md border bg-(image:--ramp)"
        style={{
          "--ramp": `linear-gradient(to right, ${layer.colors.join(", ")})`,
        }}
      />
      <div className="flex justify-between text-xs text-muted-foreground tabular-nums">
        <span>{number.format(min)}</span>
        <span>{layer.units}</span>
        <span>{number.format(max)}</span>
      </div>
    </div>
  )
}
