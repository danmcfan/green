import { describe, expect, test } from "bun:test"
import { regionOutline } from "@/lib/region"

describe("regionOutline", () => {
  test("is a closed ring around the Region's bounds", () => {
    const outline = regionOutline({
      minLon: -92,
      minLat: 42.5,
      maxLon: -90.5,
      maxLat: 43.5,
    })

    expect(outline.geometry).toEqual({
      type: "LineString",
      coordinates: [
        [-92, 42.5],
        [-90.5, 42.5],
        [-90.5, 43.5],
        [-92, 43.5],
        [-92, 42.5],
      ],
    })
  })
})
