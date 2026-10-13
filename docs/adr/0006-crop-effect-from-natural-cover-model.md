# Crop effect from the natural-cover model, not a second model

> **Changed 2026-10 ([#15](https://github.com/danmcfan/green/issues/15)):** farm land now comes from NLCD land cover, not the Cropland Data Layer. See "Farm land from NLCD land cover" below. The Crop type rules in the next two paragraphs no longer apply.

We want to see how crops change NDVI compared with natural land. We do not train a crop model. We run the natural-cover model on farm cells and take the Crop effect as Observed NDVI minus Predicted NDVI. Crop type comes from the USDA Cropland Data Layer, so the cropland branch starts in 2008. A cell is used only when it has a Crop type. It takes one of 9 crop groups (corn, soybeans, winter wheat, spring wheat, cotton, alfalfa, other hay/pasture, rice, other crops) when that group covers 75% or more of it. Failing that, it takes the Crop type "Corn/soybean" when corn and soybeans together cover 75% or more of it. Otherwise it has no Crop type and no Crop effect. The natural-cover model never sees farm land, so we check whether it can be trusted there by measuring its error on natural cells next to farm land, using the same spatial block and year holdouts, and we show that error for each region next to the Crop effect.

## Corn/soybean rotation

Added in [#10](https://github.com/danmcfan/green/issues/10). Most Corn Belt farm land grows corn and soybeans in rotation, so most cells there are mixed and failed the 75% rule for one group: in the first real run (Driftless Area, 2012) only 2 cells passed, and on 2012 data for the Upper Midwest 184 of 25,599 farm cells passed, against 9,433 with the rotation. A cell with 75% or more of one group still takes that group, so a cell with 80% corn is "Corn", not "Corn/soybean". The rotation is a Crop type only: crop shares are still fetched as the 9 crop groups. It does not go against the rejected "majority crop" option below, because the Crop effect of a rotation cell is given to the rotation, not to one crop, and the rotation is how that land is farmed. Splitting it between corn and soybeans would still need a second model.

## Farm land from NLCD land cover

Decided in [#15](https://github.com/danmcfan/green/issues/15). Crop shares from the Cropland Data Layer took about 1 h 20 min per year for CONUS, about 85% of the extract time, and the model does not use them. Now a cell is farm land when its main NLCD 2021 land cover class is farm (81 pasture/hay or 82 cultivated crops). The Crop effect is Observed minus Predicted NDVI on those cells, for every year, with no split by crop. The Crop type layer and the Corn/soybean rotation are removed. The Error next to farm land uses the same farm cells. The farm cells do not change by year, so a field that changed use after 2021 has the wrong class. We can add crop groups again when we need them.

## Considered Options

- Second model with crop type as an Input layer: rejected because it predicts crop NDVI but does not show the difference from natural land directly.
- Coarse "cultivated" class for 2001–2007: rejected because a change of source would put a false jump in the series.
- Majority crop or crop shares for mixed cells: rejected because the Crop effect of a mixed cell cannot be given to one crop without a second model.
- Lower the 75% share (e.g. to 50%) to keep more Corn Belt cells: rejected because each cell's Crop effect would mix in more of the other crops ([#10](https://github.com/danmcfan/green/issues/10)).
