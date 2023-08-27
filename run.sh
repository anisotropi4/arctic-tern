#!/usr/bin/env bash

if [ ! -d venv ]; then
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install --upgrade wheel
    if [ -s requirements.txt ]; then
        pip install --upgrade -r requirements.txt | tee setup.txt
    fi
fi

source venv/bin/activate

if [ ! -s sk-output.gpkg ]; then
    ./skeletonize.py data/rnet_princes_street.geojson sk-output.gpkg
fi

if [ ! -s vr-output.gpkg ]; then
    ./voronoi.py data/rnet_princes_street.geojson vr-output.gpkg
fi

OGR2OGR=$(which ogr2ogr)

if [ x"${OGR2OGR}" != x ]; then
    for k in sk vr
    do
        ogr2ogr -f GeoJSON ${k}-line.geojson ${k}-output.gpkg line
        sed -i 's/00000[0-9]*//g' ${k}-output.gpkg line
    done
fi
