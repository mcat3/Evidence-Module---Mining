import os

# A system-wide PostgreSQL/PostGIS install exports PROJ_LIB/GDAL_DATA pointing at its own, older
# PROJ database, which breaks EPSG lookups in rasterio/pyproj wheels. Use the bundled data instead.
for _var in ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA"):
    os.environ.pop(_var, None)
