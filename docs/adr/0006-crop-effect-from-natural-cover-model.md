# Crop effect from the natural-cover model, not a second model

We want to see how crops change NDVI compared with natural land. We do not train a crop model. We run the natural-cover model on farm cells and take the Crop effect as Observed NDVI minus Predicted NDVI. Crop type comes from the USDA Cropland Data Layer, so the cropland branch starts in 2008. A cell is used only when one of 9 crop groups (corn, soybeans, winter wheat, spring wheat, cotton, alfalfa, other hay/pasture, rice, other crops) covers 75% or more of it. The natural-cover model never sees farm land, so we check whether it can be trusted there by measuring its error on natural cells next to farm land, using the same spatial block and year holdouts, and we show that error for each region next to the Crop effect.

## Considered Options

- Second model with crop type as an Input layer: rejected because it predicts crop NDVI but does not show the difference from natural land directly.
- Coarse "cultivated" class for 2001–2007: rejected because a change of source would put a false jump in the series.
- Majority crop or crop shares for mixed cells: rejected because the Crop effect of a mixed cell cannot be given to one crop without a second model.
