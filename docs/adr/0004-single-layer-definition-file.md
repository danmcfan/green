# One JSON Layer definition file shared by backend and frontend

Every layer's id, units, value range and colors are defined once, in one JSON file at the repo root. The Python pipeline and the TypeScript frontend both read this file. The two earlier projects named the same layer differently (`bulkdens`/`b0` vs `bulk_density_0`), and nothing connected them. JSON was chosen over YAML because both sides read it without an extra dependency.
