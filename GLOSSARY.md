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
The single record of a layer's id, units, value range and colors (and, for a layer of categories such as Crop type, their names), shared by every part of the project.
_Avoid_: Layer config, layer schema

**Crop effect**:
How much greener or less green a crop makes a place than natural land would be: Observed NDVI minus the Predicted NDVI for natural land, for a place and month.
_Avoid_: Crop gap, NDVI difference, anomaly

**NDVI residual**:
Observed NDVI minus Predicted NDVI on natural land, for a place and month; where the model is wrong.
_Avoid_: Error map, anomaly

**Derived layer**:
A layer calculated from other layers rather than measured or predicted directly: the NDVI residual, Crop type and Crop effect.
