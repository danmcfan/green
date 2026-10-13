# Green

Predicts how green the land is from soil and climate, and shows the inputs, the observed greenness, and the prediction on a web map.

## Language

**Input layer**:
A soil or climate data set that the model uses to predict NDVI.
_Avoid_: Feature, predictor, covariate

**Observed NDVI**:
NDVI measured by satellite for a place and month.
_Avoid_: Actual NDVI, true NDVI, ground truth

**Predicted NDVI**:
NDVI calculated by the model from the input layers for a place and month.
_Avoid_: Estimated NDVI, modelled NDVI

**Layer definition**:
The single record of a layer's id, units, value range and colors (and, for a layer of categories, their names), shared by every part of the project.
_Avoid_: Layer config, layer schema

**Crop effect**:
How much greener or less green a crop makes a place than natural land would be: Observed NDVI minus the Predicted NDVI for natural land, for a place and month.
_Avoid_: Crop gap, NDVI difference, anomaly

**NDVI residual**:
Observed NDVI minus Predicted NDVI on natural land, for a place and month; where the model is wrong.
_Avoid_: Error map, anomaly

**Departure**:
Observed NDVI minus the mean Observed NDVI for the same place and month in the training years; how unusual a year is. Only a place with a history has one.
_Avoid_: Anomaly

**Error next to farm land**:
How wrong Predicted NDVI is on natural land next to farm land, as the RMSE over every month in each spatial block. It is measured on unseen places, unseen years and both, and the map shows the largest of the three. A Crop effect smaller than this cannot be told apart from model error.

**Spatial block**:
A square of land (200 km by default) that the model is scored on without having seen it; the Error next to farm land is given for each one.
_Avoid_: Region (that is the area a pipeline run covers, such as `small` or `conus`)

**Derived layer**:
A layer calculated from other layers rather than measured or predicted directly: the NDVI residual, Crop effect and Error next to farm land.
