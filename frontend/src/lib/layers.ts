// Typed view of the shared Layer definition file (ADR 0004).
import file from '../../../layers.json'

export type LayerKind = 'input' | 'observed' | 'predicted' | 'derived'

export interface LayerDefinition {
  id: string
  name: string
  kind: LayerKind
  units: string
  range: [number, number]
  colors: string[]
  // Names of the classes 0, 1, 2… for a layer whose values are classes, not amounts.
  categories?: string[]
}

export const layers = file.layers as LayerDefinition[]

export type GroupId = 'soil' | 'climate' | 'ndvi' | 'crops'

export const GROUPS: { id: GroupId; label: string }[] = [
  { id: 'soil', label: 'Soil' },
  { id: 'climate', label: 'Climate' },
  { id: 'ndvi', label: 'NDVI' },
  { id: 'crops', label: 'Crops' },
]

// Soil and climate Input layers are named by prefix in the pipeline too (sources.py).
export function groupOf(layer: LayerDefinition): GroupId {
  if (layer.id.startsWith('soil_')) return 'soil'
  if (layer.id.startsWith('climate_')) return 'climate'
  if (layer.id.startsWith('crop_')) return 'crops'
  return 'ndvi'
}
