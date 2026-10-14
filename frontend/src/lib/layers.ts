// Typed view of the shared Layer definition file (ADR 0004).
import { z } from "zod"
import file from "../../../layers.json"

const LayerDefinition = z.object({
  id: z.string(),
  name: z.string(),
  kind: z.enum(["input", "observed", "predicted", "derived"]),
  units: z.string(),
  range: z.tuple([z.number(), z.number()]),
  colors: z.array(z.string()),
  // Names of the classes 0, 1, 2… for a layer whose values are classes, not amounts.
  categories: z.array(z.string()).optional(),
})

export type LayerDefinition = z.infer<typeof LayerDefinition>

export const layers = z
  .object({ layers: z.array(LayerDefinition) })
  .parse(file).layers

export function layerOf(id: string): LayerDefinition {
  const layer = layers.find((l) => l.id === id)
  if (!layer) throw new Error(`No layer ${id} in layers.json`)
  return layer
}

export type GroupId = "soil" | "climate" | "ndvi" | "crops"

export const GROUPS: { id: GroupId; label: string }[] = [
  { id: "soil", label: "Soil" },
  { id: "climate", label: "Climate" },
  { id: "ndvi", label: "NDVI" },
  { id: "crops", label: "Crops" },
]

// Soil and climate Input layers are named by prefix in the pipeline too (sources.py).
export function groupOf(layer: LayerDefinition): GroupId {
  if (layer.id.startsWith("soil_")) return "soil"
  if (layer.id.startsWith("climate_")) return "climate"
  if (layer.id.startsWith("crop_")) return "crops"
  return "ndvi"
}
