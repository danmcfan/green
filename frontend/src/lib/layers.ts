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
}

export const layers = file.layers as LayerDefinition[]
