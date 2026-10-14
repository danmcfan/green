import type { Feature, LineString } from "geojson"

/** A Region's edges in degrees, as a PMTiles header gives them. */
export type Region = {
  minLon: number
  minLat: number
  maxLon: number
  maxLat: number
}

/** The edge of the Region, so places outside it read as not modelled rather than broken. */
export function regionOutline(b: Region): Feature<LineString> {
  return {
    type: "Feature",
    properties: {},
    geometry: {
      type: "LineString",
      coordinates: [
        [b.minLon, b.minLat],
        [b.maxLon, b.minLat],
        [b.maxLon, b.maxLat],
        [b.minLon, b.maxLat],
        [b.minLon, b.minLat],
      ],
    },
  }
}
