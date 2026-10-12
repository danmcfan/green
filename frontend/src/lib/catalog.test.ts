import { describe, expect, test } from 'bun:test'
import { pickMap, readCatalog, tileUrl } from '@/lib/catalog'

describe('readCatalog', () => {
  test('a monthly layer lists the years it has maps for', () => {
    const catalog = readCatalog([
      'observed_ndvi__2012-01.pmtiles',
      'observed_ndvi__2011-07.pmtiles',
      'observed_ndvi__2012-07.pmtiles',
    ])

    expect(catalog.get('observed_ndvi')).toMatchObject({ monthly: true, years: [2011, 2012] })
  })

  test('a soil layer has one map and no years', () => {
    const catalog = readCatalog(['soil_clay_0cm__soil_clay_0cm.pmtiles'])

    expect(catalog.get('soil_clay_0cm')).toEqual({
      names: ['soil_clay_0cm'],
      years: [],
      monthly: false,
    })
  })
})

describe('pickMap', () => {
  const ndvi = readCatalog([
    'observed_ndvi__2011-06.pmtiles',
    'observed_ndvi__2011-07.pmtiles',
    'observed_ndvi__2012-07.pmtiles',
  ]).get('observed_ndvi')!

  test('a monthly layer shows the map for the chosen year and month', () => {
    expect(pickMap(ndvi, { year: 2011, month: 6 })).toEqual({ name: '2011-06', year: 2011, month: 6 })
  })

  test('a month with no map falls back to the nearest month that has one', () => {
    expect(pickMap(ndvi, { year: 2012, month: 5 })).toEqual({ name: '2012-07', year: 2012, month: 7 })
    expect(pickMap(ndvi, { year: 2001, month: 1 })).toEqual({ name: '2011-06', year: 2011, month: 6 })
    expect(pickMap(ndvi, { year: 2025, month: 12 })).toEqual({ name: '2012-07', year: 2012, month: 7 })
  })

  test('a yearly layer shows the nearest year and ignores the month', () => {
    const cropType = readCatalog([
      'crop_type__2011.pmtiles',
      'crop_type__2012.pmtiles',
    ]).get('crop_type')!

    expect(pickMap(cropType, { year: 2012, month: 7 })).toEqual({ name: '2012', year: 2012 })
    expect(pickMap(cropType, { year: 2001, month: 7 })).toEqual({ name: '2011', year: 2011 })
  })

  test('a soil layer always shows its one map', () => {
    const soil = readCatalog(['soil_ph_0cm__soil_ph_0cm.pmtiles']).get('soil_ph_0cm')!

    expect(pickMap(soil, { year: 2012, month: 7 })).toEqual({ name: 'soil_ph_0cm' })
  })
})

describe('tileUrl', () => {
  test('points the pmtiles protocol at tiles/<layer>__<map>.pmtiles under the site', () => {
    expect(tileUrl('https://danmcfan.github.io/green/', 'observed_ndvi', '2012-07')).toBe(
      'pmtiles://https://danmcfan.github.io/green/tiles/observed_ndvi__2012-07.pmtiles',
    )
  })
})
