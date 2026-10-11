# Static site on GitHub Pages, no server

The app is a static site on GitHub Pages: every map is computed ahead of time by the pipeline, and the browser only reads files. We chose this over a live API (custom areas or dates on request) because a server brings model serving, Earth Engine calls at request time and hosting costs before the model has earned trust. A server can be added later; until then, anything the map shows must exist as a precomputed file.
